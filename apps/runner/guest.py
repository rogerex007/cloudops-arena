"""Trusted guest init: input is read-only, Terraform runs as an unprivileged UID."""
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time
import urllib.request

import hcl2
from policy import FILES, PREFIX, VALIDATOR, VALIDATORS, RUNTIME_VALIDATOR, RESILIENCE_VALIDATOR, inspect_hcl, inspect_plan
from progress import curated

PROGRESS=None
ACTIVE_STAGE=None


def emit(stage,status):
    global ACTIVE_STAGE
    ACTIVE_STAGE=stage if status=='running' else None
    value=curated(stage,status)
    PROGRESS.write(json.dumps({'stage':value['stage'],'status':value['status']})+'\n')
    PROGRESS.flush()


def limits():
    os.setgroups([])
    os.setgid(2000)
    os.setuid(2000)
    resource.setrlimit(resource.RLIMIT_FSIZE, (16*1024*1024, 16*1024*1024))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))


def runtime_guest(working,result):
    from runtime import evaluate_runtime
    for directory,_folders,files in os.walk(working):
        os.chown(directory,2000,2000)
        for filename in files:os.chown(Path(directory)/filename,2000,2000)
    Path('/work/home').mkdir();os.chown('/work/home',2000,2000)
    env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/work/home','AWS_ACCESS_KEY_ID':'test',
        'AWS_SECRET_ACCESS_KEY':'test','AWS_DEFAULT_REGION':'us-east-1','AWS_EC2_METADATA_DISABLED':'true',
        'PYTHONDONTWRITEBYTECODE':'1'}
    Path('/work/floci').mkdir()
    with open('/work/floci.log','wb') as log:
        floci=subprocess.Popen(['/opt/arena/floci','-Dquarkus.http.host=127.0.0.1'],cwd='/work/floci',stdout=log,stderr=log)
        try:
            emit('floci','running')
            for _ in range(40):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:4566',timeout=1):break
                except urllib.error.HTTPError:break
                except OSError:
                    if floci.poll() is not None:raise RuntimeError('Floci unavailable')
                    time.sleep(0.5)
            else:raise RuntimeError('Floci startup timeout')
            emit('floci','passed')
            resilience=result["validator"]==RESILIENCE_VALIDATOR
            evidence=evaluate_runtime(working,env,limits,emit,resilience=resilience)
            evidence['network_interfaces']=sorted(path.name for path in Path('/sys/class/net').iterdir())
            result.update(status='passed',result_code='resilience_flow_passed' if resilience else 'runtime_flow_passed',
                message='Duplicados, lotes parciales, reintentos SQS, DLQ y recuperación verificados con operaciones simuladas en una VM aislada.' if resilience else 'Las funciones procesaron dos órdenes con DynamoDB, EventBridge y SQS en una VM aislada. Los handlers se invocaron como procesos sin privilegios; no se desplegaron Lambdas.',evidence=evidence)
            return result
        finally:
            floci.terminate()
            try:floci.wait(timeout=5)
            except subprocess.TimeoutExpired:floci.kill();floci.wait()


def evaluate():
    subprocess.run(["mount", "-o", "ro,nodev,nosuid,noexec", "/dev/sr0", "/input"], check=True, timeout=10)
    request = json.loads(Path('/input/request.json').read_text())
    result = {"run_id": request['run_id'], "source_digest": request['source_digest'], "validator": request.get("validator",VALIDATOR)}
    try:
        actual = {}
        for name in VALIDATORS[result["validator"]]:
            source = Path('/input/source')/name
            data = source.read_bytes()
            actual[name] = hashlib.sha256(data).hexdigest()
        digest = hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if digest != request['source_digest']:
            raise ValueError('La copia de archivos no coincide con la entrega registrada.')
        working = Path('/work/source')
        shutil.copytree('/input/source', working)
        if result['validator'] in {RUNTIME_VALIDATOR,RESILIENCE_VALIDATOR}:
            return runtime_guest(working,result)
        terraform = working/PREFIX/'terraform'
        (terraform/'.build').mkdir(exist_ok=True)
        documents = [hcl2.loads((terraform/name).read_text()) for name in ('main.tf','variables.tf','versions.tf','outputs.tf')]
        emit('policy','running')
        inspect_hcl(documents)
        emit('policy','passed')
        for directory, folders, files in os.walk(working):
            os.chown(directory,2000,2000)
            for filename in files:
                os.chown(Path(directory)/filename,2000,2000)
        Path('/work/home').mkdir()
        os.chown('/work/home',2000,2000)
        cli = Path('/opt/arena/terraform.rc')
        cli.write_text('disable_checkpoint = true\nprovider_installation { filesystem_mirror { path = "/opt/arena/providers" } }\n')
        env = {'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/work/home','TF_CLI_CONFIG_FILE':str(cli),
               'TF_IN_AUTOMATION':'1','CHECKPOINT_DISABLE':'1','AWS_ACCESS_KEY_ID':'test',
               'AWS_SECRET_ACCESS_KEY':'test','AWS_DEFAULT_REGION':'us-east-1','AWS_EC2_METADATA_DISABLED':'true'}
        Path('/work/floci').mkdir()
        log = open('/work/floci.log','wb')
        floci = subprocess.Popen(['/opt/arena/floci','-Dquarkus.http.host=127.0.0.1'],cwd='/work/floci',stdout=log,stderr=log)
        try:
            emit('floci','running')
            for _ in range(40):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:4566',timeout=1):
                        break
                except urllib.error.HTTPError:
                    break
                except OSError:
                    if floci.poll() is not None:
                        raise RuntimeError('Floci no pudo iniciar en el laboratorio.')
                    time.sleep(0.5)
            else:
                raise RuntimeError('Floci no estuvo disponible a tiempo.')
            emit('floci','passed')

            def run(stage, arguments):
                emit(stage,'running')
                with open('/work/terraform.log','wb') as output:
                    process = subprocess.run(['terraform',*arguments],cwd=terraform,env=env,stdout=output,stderr=output,preexec_fn=limits,timeout=75)
                if process.returncode:
                    emit(stage,'failed')
                    # Bounded diagnostics remain data; they never determine success.
                    diagnostic=Path('/work/terraform.log').read_text(errors='replace')[-3000:]
                    raise ValueError(stage+': '+diagnostic)
                emit(stage,'passed')
            run('format',['fmt','-recursive'])
            run('init',['init','-backend=false','-input=false','-no-color'])
            run('validate',['validate','-no-color'])
            run('plan',['plan','-input=false','-refresh=false','-lock=false','-no-color','-out=plan.bin',
                        '-var=use_floci=true','-var=endpoint_url=http://127.0.0.1:4566',
                        '-var=lambda_endpoint_url=http://127.0.0.1:4566','-var=name_prefix=arena-eval'])
            with open('/work/plan.json','wb') as output:
                shown=subprocess.run(['terraform','show','-json','plan.bin'],cwd=terraform,env=env,stdout=output,stderr=subprocess.DEVNULL,preexec_fn=limits,timeout=30)
            if shown.returncode:
                raise ValueError('No pudimos leer la evidencia del plan.')
            emit('review','running')
            evidence=inspect_plan(json.loads(Path('/work/plan.json').read_text()))
            emit('review','passed')
            evidence['network_interfaces']=sorted(path.name for path in Path('/sys/class/net').iterdir())
            result.update(status='passed',result_code='terraform_plan_passed',message='Terraform validó y generó el plan esperado en una VM aislada. No se aplicaron recursos.',evidence=evidence)
        finally:
            floci.terminate()
            try: floci.wait(timeout=5)
            except subprocess.TimeoutExpired:
                floci.kill(); floci.wait()
            log.close()
    except ValueError as exc:
        if ACTIVE_STAGE:emit(ACTIVE_STAGE,'failed')
        result.update(status='failed',result_code='resilience_validation_failed' if result['validator']==RESILIENCE_VALIDATOR else 'runtime_validation_failed' if result['validator']==RUNTIME_VALIDATOR else 'terraform_validation_failed',message=str(exc)[:3500])
    except Exception:
        result.update(status='blocked',result_code='guest_error',message='El laboratorio no pudo completar la evaluación. Reintenta o consulta con el instructor.')
    return result


if __name__=='__main__':
    channel=Path('/dev/virtio-ports/arena.result')
    os.chmod(channel,0o600)
    progress_channel=Path('/dev/virtio-ports/arena.progress')
    os.chmod(progress_channel,0o600)
    PROGRESS=progress_channel.open('w',buffering=1)
    result=evaluate()
    PROGRESS.close()
    with channel.open('w') as output:
        json.dump(result,output)
        output.flush()
