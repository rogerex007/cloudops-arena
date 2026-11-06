"""Private VM pilot: trusted template only, no browser-selected SDK operations.

The serial device is root-only. Docker and its socket exist only inside this VM.
This pilot deliberately does not accept participant code or award points.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

import boto3
import hcl2
from policy import FILES, PREFIX as SOURCE_PREFIX, inspect_hcl, inspect_plan

ROOT = Path('/work/playground')
PREFIX = 'arena-playground'
ENV = dict(os.environ, AWS_ACCESS_KEY_ID='test', AWS_SECRET_ACCESS_KEY='test',
           AWS_DEFAULT_REGION='us-east-1', AWS_EC2_METADATA_DISABLED='true',
           TF_CLI_CONFIG_FILE='/opt/arena/terraform.rc', TF_IN_AUTOMATION='1',
           CHECKPOINT_DISABLE='1', HOME='/home/learner')


def run(args, timeout=180, learner=False):
    command = ['runuser', '-u', 'learner', '--', *args] if learner else args
    result = subprocess.run(command, cwd=ROOT, env=ENV, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.decode(errors='replace')[-1800:] + result.stderr.decode(errors='replace')[-1800:])
    return result.stdout


def client(service):
    return boto3.client(service, endpoint_url='http://127.0.0.1:4566', region_name='us-east-1',
                        aws_access_key_id='test', aws_secret_access_key='test')


def inventory():
    ddb = client('dynamodb')
    return {
        'tables': sorted(ddb.list_tables()['TableNames']),
        'functions': sorted(f['FunctionName'] for f in client('lambda').list_functions()['Functions']),
        'queues': sorted(client('sqs').list_queues().get('QueueUrls', [])),
        'buses': sorted(b['Name'] for b in client('events').list_event_buses()['EventBuses']),
        'orders': ddb.scan(TableName=PREFIX+'-orders', Limit=20).get('Items', []),
        'processed': ddb.scan(TableName=PREFIX+'-idempotency', Limit=40).get('Items', []),
    }


def order(order_id):
    # Pilot accepts a bounded label, never arbitrary invocation payload/code.
    if not isinstance(order_id, str) or not 1 <= len(order_id) <= 64 or not all(c.isalnum() or c == '-' for c in order_id):
        raise ValueError('Invalid pilot order identifier')
    payload = {'body': json.dumps({'orderId': order_id, 'total': '125.00', 'customerId': 'pilot'})}
    result = client('lambda').invoke(FunctionName=PREFIX+'-orders', Payload=json.dumps(payload).encode())
    body = json.loads(result['Payload'].read())
    if result.get('FunctionError') or body.get('statusCode') != 201:
        raise RuntimeError('Managed Lambda invocation failed: '+json.dumps(body)[:1500])
    for _ in range(60):
        snap = inventory()
        completed = {item['service']['S'] for item in snap['processed'] if item.get('eventId', {}).get('S') == order_id}
        if completed == {'payments', 'inventory'}:
            return snap
        time.sleep(1)
    raise RuntimeError('Managed SQS consumers did not complete the order')


def prepare():
    # The filesystem was assembled in Docker but now runs as a complete VM.
    Path('/.dockerenv').unlink(missing_ok=True)
    Path('/run/.containerenv').unlink(missing_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT/'terraform').exists():
        participant=Path('/input/request.json').exists()
        template=Path('/input/source')/SOURCE_PREFIX if participant else Path('/opt/arena/template')
        if participant:
            request=json.loads(Path('/input/request.json').read_text())
            hashes={name:hashlib.sha256((Path('/input/source')/name).read_bytes()).hexdigest() for name in FILES}
            digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if request['source_digest']!=digest:raise ValueError('Source digest mismatch')
        shutil.copytree(template, ROOT, dirs_exist_ok=True)
        (ROOT/'terraform'/'.build').mkdir(exist_ok=True)
        for path in [ROOT, *ROOT.rglob('*')]:
            os.chown(path, 2000, 2000)
    Path('/opt/arena/terraform.rc').write_text('disable_checkpoint = true\nprovider_installation { filesystem_mirror { path = "/opt/arena/providers" } }\n')
    images = run(['docker', 'image', 'ls', '-q', 'public.ecr.aws/lambda/python:3.12'])
    if not images.strip():
        run(['docker', 'load', '-i', '/opt/arena/python-runtime.tar'], timeout=240)
    floci_env = dict(ENV, FLOCI_STORAGE_MODE='persistent',
                     FLOCI_SECURITY_ALLOW_UNSAFE_NETWORK_EXPOSURE='true',
                     FLOCI_STORAGE_PERSISTENT_PATH=str(ROOT/'data'),
                     FLOCI_SERVICES_LAMBDA_CODE_PATH=str(ROOT/'lambda-code'),
                     FLOCI_SERVICES_LAMBDA_DOCKER_HOST_OVERRIDE='172.17.0.1',
                     FLOCI_SERVICES_LAMBDA_WARM_POOL_MAX_PER_FUNCTION='1',
                     FLOCI_SERVICES_LAMBDA_WARM_POOL_MAX_TOTAL='3')
    log = (ROOT/'floci.log').open('ab')
    floci = subprocess.Popen(['/opt/arena/floci', '-Dquarkus.http.host=0.0.0.0'], cwd=ROOT, env=floci_env, stdout=log, stderr=log)
    for _ in range(60):
        try:
            client('dynamodb').list_tables()
            return floci
        except Exception:
            if floci.poll() is not None:
                raise RuntimeError('Floci startup failed: '+(ROOT/'floci.log').read_text(errors='replace')[-2500:])
            time.sleep(.5)
    raise RuntimeError('Floci startup timeout')


def deploy():
    tf = ROOT/'terraform'
    inspect_hcl([hcl2.loads((tf/name).read_text()) for name in ('main.tf', 'variables.tf', 'versions.tf', 'outputs.tf')])
    base = ['terraform', '-chdir='+str(tf)]
    run([*base, 'fmt', '-recursive'], learner=True)
    run([*base, 'init', '-backend=false', '-input=false', '-no-color'], learner=True)
    run([*base, 'validate', '-no-color'], learner=True)
    run([*base, 'plan', '-input=false', '-no-color', '-out=plan.bin',
         '-var=name_prefix='+PREFIX, '-var=use_floci=true',
         '-var=endpoint_url=http://127.0.0.1:4566', '-var=lambda_endpoint_url=http://172.17.0.1:4566'], learner=True)
    plan = json.loads(run([*base, 'show', '-json', 'plan.bin'], learner=True))
    evidence=inspect_plan(plan)
    run([*base, 'apply', '-input=false', '-no-color', 'plan.bin'], timeout=300, learner=True)
    snapshot=inventory()
    if len(snapshot['tables'])!=2 or len(snapshot['functions'])!=3 or len(snapshot['queues'])!=4:
        raise ValueError('Applied inventory does not match the reviewed lab')
    if Path('/input/request.json').exists():
        request=json.loads(Path('/input/request.json').read_text())
        evidence.update(applied=True,external_network=False)
        return {'run_id':request['run_id'],'source_digest':request['source_digest'],
            'validator':'aws-event-driven-deploy-v1','status':'passed','result_code':'terraform_deployment_passed',
            'message':'Tu infraestructura fue desplegada y verificada en tu playground privado. No se crearon recursos en AWS real.',
            'snapshot':snapshot,'evidence':evidence}
    return snapshot


def main():
    channel = Path('/dev/virtio-ports/arena.rpc')
    os.chmod(channel, 0o600)
    with channel.open('r+b', buffering=0) as stream:
        try:
            floci = prepare()
            stream.write(json.dumps({'ready': True}).encode()+b'\n')
        except Exception as exc:
            stream.write(json.dumps({'ready': False, 'error': str(exc)}).encode()+b'\n')
            return
        try:
            while True:
                raw = bytearray()
                while not raw.endswith(b'\n'):
                    chunk = stream.read(1)
                    if not chunk:
                        time.sleep(.1)
                        continue
                    raw.extend(chunk)
                    if len(raw) > 1024:
                        raise ValueError('RPC size limit')
                try:
                    request = json.loads(raw)
                    command = request.get('command')
                    if command == 'deploy': result = deploy()
                    elif command == 'ensure':
                        marker = ROOT/'provisioned'
                        if not marker.exists():
                            deploy()
                            marker.touch(mode=0o600)
                        result = inventory()
                    elif command == 'inventory': result = inventory()
                    elif command == 'order': result = order(request.get('order_id'))
                    elif command == 'shutdown':
                        floci.terminate()
                        floci.wait(timeout=30)
                        subprocess.run(['systemctl', 'poweroff'], check=True)
                        return
                    else: raise ValueError('Unsupported pilot command')
                    response = {'ok': True, 'result': result}
                except Exception as exc:
                    response = {'ok': False, 'error': str(exc)[:4000]}
                stream.write(json.dumps(response).encode()+b'\n')
        finally:
            if floci.poll() is None:
                floci.terminate()
                floci.wait(timeout=30)


if __name__ == '__main__':
    main()
