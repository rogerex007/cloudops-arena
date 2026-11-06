"""Claim deliveries and delegate authorized Terraform plans to an isolated VM."""
import json
import base64
import hashlib
import logging
import re
import signal
import time
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from boto3.dynamodb.conditions import Attr
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .config import settings
from .evaluation_validators import accepts
from .db import dynamodb_client, get_item, scan_items, table_resource
from .gamepack import get_mission, load_pack
from .evaluation_progress import curated
from .evaluations import QUEUE_KEY, queued_order

logger = logging.getLogger("arena-evaluation-worker")
LEASE_SECONDS = 120
VALIDATOR_VERSION = "repository-preflight-v1"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class GitHubReadError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def github_json(path):
    # Repository names and SHAs are validated before constructing this path.
    request = Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "CloudOpsArena-Evaluator",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            body = response.read(4 * 1024 * 1024 + 1)
    except HTTPError as exc:
        if exc.code in {404, 422}:
            raise GitHubReadError("source_unavailable", "No pudimos acceder a ese commit. Comprueba el SHA y que el repositorio sea público; el acceso privado aún no está conectado.") from exc
        if exc.code in {403, 429}:
            raise GitHubReadError("github_rate_limit", "GitHub rechazó temporalmente la consulta o alcanzó su límite. Reintenta más tarde.") from exc
        raise GitHubReadError("github_unavailable", "No pudimos consultar GitHub. Reintenta más tarde.") from exc
    except (URLError, OSError):
        raise GitHubReadError("github_unavailable", "No pudimos conectar con GitHub. Reintenta más tarde.")
    if len(body) > 4 * 1024 * 1024:
        raise GitHubReadError("source_too_large", "El repositorio supera el tamaño admitido para esta revisión.")
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise GitHubReadError("github_invalid_response", "GitHub devolvió una respuesta que no pudimos verificar.")


def inspect_source(item, read_github=github_json):
    """Only negative/blocked results: file presence cannot earn lab points."""
    repo, sha = item.get("repo_name", ""), item.get("commit_sha", "")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        return {"status": "failed", "result_code": "invalid_source", "message": "El repositorio o el SHA registrado no es válido."}
    pack = load_pack(item["game_pack"])
    if str(pack.get("version", "")) != str(item["pack_version"]):
        return {"status": "blocked", "result_code": "pack_changed", "message": "La versión del reto cambió. Consulta con el instructor antes de reenviar la entrega."}
    mission = get_mission(pack, item["mission_id"])
    requirements = (mission or {}).get("evaluation", {}).get("required_files", [])
    if not requirements:
        return {"status": "blocked", "result_code": "validator_unavailable", "message": "Esta misión todavía no tiene una revisión automática configurada."}
    try:
        commit = read_github(f"/repos/{repo}/git/commits/{sha}")
        tree_sha = commit.get("tree", {}).get("sha", "")
        if commit.get("sha") != sha or not re.fullmatch(r"[a-f0-9]{40}", tree_sha):
            raise GitHubReadError("commit_mismatch", "No pudimos verificar el commit exacto de esta entrega.")
        tree = read_github(f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
        if tree.get("sha") != tree_sha or tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise GitHubReadError("incomplete_tree", "GitHub no devolvió el árbol completo de archivos para este commit.")
        files = {entry["path"] for entry in tree["tree"]
                 if entry.get("type") == "blob" and entry.get("mode") in {"100644", "100755"}}
    except GitHubReadError as exc:
        return {"status": "blocked", "result_code": exc.code, "message": exc.message}
    missing = sorted(set(requirements) - files)
    if missing:
        return {"status": "failed", "result_code": "missing_files", "missing_files": missing[:20],
                "message": "El commit no contiene todos los archivos del laboratorio. Revisa la lista, sube los archivos y registra el nuevo commit."}
    return {"status": "blocked", "result_code": "isolated_runner_required",
            "message": "Los archivos requeridos están presentes. Falta habilitar el runner aislado y verificar el acceso al repositorio para evaluar Terraform. Esta revisión no concede puntos."}


def claim(item, now=None):
    now = int(time.time()) if now is None else now
    token = uuid.uuid4().hex
    lease_seconds = 600 if settings.evaluation_runner_url else LEASE_SECONDS
    try:
        table_resource().update_item(
            Key={"PK": item["PK"], "SK": item["SK"]},
            UpdateExpression="SET #state = :preparing, lease_token = :token, lease_expires_at = :expires, updated_at = :updated, message = :message",
            ConditionExpression="#state = :pending",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":pending": "pending", ":preparing": "preparing", ":token": token,
                ":expires": now + lease_seconds, ":updated": timestamp(), ":message": "Comprobando el commit y los archivos en GitHub."},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    return {**item, "status": "preparing", "lease_token": token, "lease_expires_at": now + lease_seconds}


def finish(item, result, *, expired=False, score=True):
    if item.get('operation')=='plan':score=False
    passed = result.get('status') == 'passed'
    if passed and item.get('operation')=='deploy' and (result.get('validator')!='aws-event-driven-deploy-v1' or result.get('evidence',{}).get('applied') is not True):
        raise ValueError('Deployment requires verified apply evidence')
    if passed and not (item.get('repository_verified') is True and item.get('status') == 'running' and accepts(item['mission_id'],result.get('validator'),result.get('result_code'))):
        raise ValueError('Only the authorized isolated validator can approve a mission')
    if result.get("status") not in {"failed", "blocked", "passed"}:
        raise ValueError("Invalid evaluation result")
    pk = item["PK"]
    finished = timestamp()
    fields = {**result, "updated_at": finished, "finished_at": finished, "validator_version": result.get('validator', VALIDATOR_VERSION)}
    points = 0
    if passed and score:
        pack = load_pack(item['game_pack'])
        mission = get_mission(pack, item['mission_id'])
        if str(pack['version']) != str(item['pack_version']) or not mission:
            raise ValueError('Game Pack version changed during evaluation')
        points = int(mission.get('workflow_points', mission.get('points', 0)))
    if passed:
        fields['points_awarded'] = points
    names = {"#state": "status"}
    values = {":active": {"S": item.get('status', 'preparing')}, ":token": {"S": item["lease_token"]}}
    assignments = []
    for index, (key, value) in enumerate(fields.items()):
        name, placeholder = f"#field{index}", f":value{index}"
        names[name] = key
        values[placeholder] = TypeSerializer().serialize(value)
        assignments.append(f"{name} = {placeholder}")
    expression = "#state = :active AND lease_token = :token"
    if expired:
        expression += " AND lease_expires_at <= :now"
        values[":now"] = {"N": str(int(time.time()))}
    if not expired:
        expression += ' AND lease_expires_at > :now'
        values[':now']={'N':str(int(time.time()))}
    client = dynamodb_client()
    try:
        operations=[
            {"Update": {"TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": pk}, "SK": {"S": item["SK"]}},
                "UpdateExpression": "SET " + ", ".join(assignments) + " REMOVE lease_token, lease_expires_at",
                "ConditionExpression": expression,
                "ExpressionAttributeNames": names, "ExpressionAttributeValues": values}},
            {"Delete": {"TableName": settings.dynamodb_table_name,
                "Key": {"PK": {"S": pk}, "SK": {"S": f"EVALLOCK#{item['team_id']}"}},
                "ConditionExpression": "evaluation_id = :evaluation",
                "ExpressionAttributeValues": {":evaluation": {"S": item["evaluation_id"]}}}},
        ]
        if passed and item.get('operation')=='deploy':
            deployment=result.get('deployment',{})
            if deployment.get('evaluation_id')!=item['evaluation_id'] or deployment.get('commit_sha')!=item['commit_sha'] or deployment.get('source_digest')!=item.get('source_digest'):
                raise ValueError('Deployment provenance mismatch')
            receipt={'PK':pk,'SK':f"DEPLOY#{item['team_id']}",'type':'deployment',
                'team_id':item['team_id'],'repo_name':item['repo_name'],'status':'applied',
                'validator':result['validator'],'created_at':finished,**deployment}
            operations.append({'Put':{'TableName':settings.dynamodb_table_name,
                'Item':{k:TypeSerializer().serialize(v) for k,v in receipt.items()}}})
            operations.append({'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                'Key':{'PK':{'S':pk},'SK':{'S':'META'}},'ConditionExpression':'#s = :open',
                'ExpressionAttributeNames':{'#s':'status'},'ExpressionAttributeValues':{':open':{'S':'open'}}}})
            if not score:
                for sk,expression,parameters in [
                    (f"TEAM#{item['team_id']}",'repo_name = :repo',{':repo':item['repo_name']}),
                    (f"USER#{item['participant_id']}",'team_id = :team',{':team':item['team_id']}),
                    (f"GHAUTH#{item['team_id']}",'repository_id = :repo AND installation_id = :install',{':repo':item['repository_id'],':install':item['installation_id']})]:
                    operations.append({'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                        'Key':{'PK':{'S':pk},'SK':{'S':sk}},'ConditionExpression':expression,
                        'ExpressionAttributeValues':{k:TypeSerializer().serialize(v) for k,v in parameters.items()}}})
                if item['authorized_participant_id']!=item['participant_id']:
                    operations.append({'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                        'Key':{'PK':{'S':pk},'SK':{'S':f"USER#{item['authorized_participant_id']}"}},
                        'ConditionExpression':'team_id = :team','ExpressionAttributeValues':{':team':{'S':item['team_id']}}}})
        if passed and score:
            submission={'PK':pk,'SK':f"SUB#{item['team_id']}#{item['mission_id']}", 'type':'submission',
                'team_id':item['team_id'],'mission_id':item['mission_id'],'status':'passed','points':points,
                'source':'isolated-runner','run_id':result['run_id'],'commit_sha':item['commit_sha'],
                'validator':result['validator'],'created_at':finished}
            operations.extend([
                {'Put':{'TableName':settings.dynamodb_table_name,'Item':{k:TypeSerializer().serialize(v) for k,v in submission.items()},'ConditionExpression':'attribute_not_exists(PK)'}},
                {'Update':{'TableName':settings.dynamodb_table_name,
                    'Key':{'PK':{'S':pk},'SK':{'S':f"TEAM#{item['team_id']}"}},
                    'UpdateExpression':'SET score = if_not_exists(score, :zero) + :points, updated_at = :now',
                    'ConditionExpression':'repo_name = :repo',
                    'ExpressionAttributeValues':{':zero':{'N':'0'},':points':{'N':str(points)},':now':{'S':finished},':repo':{'S':item['repo_name']}}}},
                {'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                    'Key':{'PK':{'S':pk},'SK':{'S':f"USER#{item['participant_id']}"}},
                    'ConditionExpression':'team_id = :team','ExpressionAttributeValues':{':team':{'S':item['team_id']}}}},
                {'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                    'Key':{'PK':{'S':pk},'SK':{'S':f"GHAUTH#{item['team_id']}"}},
                    'ConditionExpression':'repository_id = :repo AND installation_id = :installation',
                    'ExpressionAttributeValues':{':repo':{'N':str(item['repository_id'])},':installation':{'N':str(item['installation_id'])}}}},
            ])
            if item['authorized_participant_id'] != item['participant_id']:
                operations.append({'ConditionCheck':{'TableName':settings.dynamodb_table_name,
                    'Key':{'PK':{'S':pk},'SK':{'S':f"USER#{item['authorized_participant_id']}"}},
                    'ConditionExpression':'team_id = :team','ExpressionAttributeValues':{':team':{'S':item['team_id']}}}})
        if item.get('queue_accounted'):
            operations.append({'Update':{'TableName':settings.dynamodb_table_name,
                'Key':{key:{'S':value} for key,value in QUEUE_KEY.items()},
                'UpdateExpression':'SET outstanding = outstanding - :one',
                'ConditionExpression':'outstanding >= :one','ExpressionAttributeValues':{':one':{'N':'1'}}}})
        client.transact_write_items(TransactItems=operations)
    except client.exceptions.TransactionCanceledException:
        if passed and score and get_item(pk,f"SUB#{item['team_id']}#{item['mission_id']}"):
            return finish(item,result,score=False)
        # Includes lease loss/retry races. Never release another request's slot.
        return False
    logger.info("evaluation=%s status=%s result=%s", item["evaluation_id"], result["status"], result["result_code"])
    return True


def internal_json(url, secret, payload, timeout):
    request=Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+secret})
    try:
        with build_opener(NoRedirect).open(request,timeout=timeout) as response:
            data=response.read(3*1024*1024+1)
        if len(data)>3*1024*1024: raise ValueError('Oversized executor response')
        return json.loads(data)
    except HTTPError as exc:
        try: detail=json.loads(exc.read(16000)).get('detail')
        except (ValueError,OSError): detail=None
        if isinstance(detail,dict) and detail.get('status')=='failed':
            return {'error_result':detail}
        return {'error_result':{'status':'blocked','retryable':exc.code in {409,429} or exc.code>=500,'result_code':'execution_unavailable',
            'message':detail if isinstance(detail,str) else 'El ejecutor aislado no está disponible. Reintenta más tarde.'}}


def execute_plan(claimed):
    from pathlib import Path
    from urllib.parse import quote
    secret=Path(settings.evaluation_runner_token_file).read_text().strip()
    record_progress(claimed,{'stage':'source','status':'running'})
    path=f"/internal/evaluations/{quote(claimed['event_id'],safe='')}/{quote(claimed['evaluation_id'],safe='')}/source"
    source=internal_json(settings.evaluation_internal_api_url+path,secret,{'lease_token':claimed['lease_token']},180)
    if source.get('error_result'): return source['error_result']
    if source.get('repository_verified') is not True or not accepts(claimed['mission_id'],source.get('validator')):
        raise ValueError('Source authorization missing')
    record_progress(claimed,{'stage':'source','status':'passed'})
    hashes={path:hashlib.sha256(base64.b64decode(content,validate=True)).hexdigest() for path,content in source['files'].items()}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    table_resource().update_item(Key={'PK':claimed['PK'],'SK':claimed['SK']},
        UpdateExpression='SET #s = :running, repository_verified = :verified, source_digest = :digest, message = :message',
        ConditionExpression='#s = :preparing AND lease_token = :token AND lease_expires_at > :now',
        ExpressionAttributeNames={'#s':'status'},
        ExpressionAttributeValues={':running':'running',':verified':True,':digest':digest,':message':'Desplegando el commit verificado en tu VM privada.' if claimed.get('operation')=='deploy' else 'Evaluando la misión en una VM desechable sin red externa.',
            ':preparing':'preparing',':token':claimed['lease_token'],':now':int(time.time())})
    claimed.update(status='running',repository_verified=True,repository_id=source['repository_id'],
        installation_id=source['installation_id'],authorized_participant_id=source['authorized_participant_id'])
    claimed['source_digest']=digest
    if claimed.get('operation')=='deploy':
        if not settings.playground_manager_url:raise ValueError('Deployment manager not configured')
        record_progress(claimed,{'stage':'apply','status':'running'})
        result=internal_json(settings.playground_manager_url+'/deploy',secret,
            {'event_id':claimed['event_id'],'team_id':claimed['team_id'],'evaluation_id':claimed['evaluation_id'],
             'commit_sha':claimed['commit_sha'],'source_digest':digest,'files':source['files'],'attempt':int(claimed.get('attempt',1))},480)
        record_progress(claimed,{'stage':'apply','status':'passed' if result.get('status')=='passed' else 'failed'})
    else:
        result=runner_stream(settings.evaluation_runner_url+'/evaluate',secret,{'validator':source['validator'],'files':source['files']},claimed)
    if result.get('error_result'): return result['error_result']
    if result.get('source_digest')!=digest or result.get('validator')!=source['validator'] or result.get('status') not in {'passed','failed','blocked'} or not re.fullmatch(r'[a-f0-9]{32}',result.get('run_id','')):
        raise ValueError('Executor evidence does not match submitted source')
    if result['status']=='failed':
        active=next((event for event in reversed(claimed.get('progress',[])) if event['stage']!='cleanup'),None)
        if active and active['status']=='running':
            record_progress(claimed,{'stage':active['stage'],'status':'failed'})
    return result


def record_progress(claimed,event):
    value=curated(event.get('stage'),event.get('status'))
    value['timestamp']=timestamp()
    progress=[*claimed.get('progress',[]),value][-64:]
    table_resource().update_item(Key={'PK':claimed['PK'],'SK':claimed['SK']},
        UpdateExpression='SET progress = :progress, updated_at = :now',
        ConditionExpression='#s IN (:preparing, :running) AND lease_token = :token AND lease_expires_at > :expires',
        ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={
            ':progress':progress,':now':value['timestamp'],':preparing':'preparing',
            ':running':'running',':token':claimed['lease_token'],':expires':int(time.time())})
    claimed['progress']=progress


def open_runner(request):
    # A previous VM may still be cleaning up or finishing after lease recovery.
    # Keep this wait inside the existing 600-second execution lease.
    deadline=time.monotonic()+60
    while True:
        try:return build_opener(NoRedirect).open(request,timeout=300)
        except HTTPError as error:
            if error.code!=409 or time.monotonic()>=deadline:raise
            error.close()
            time.sleep(3)


def runner_stream(url,secret,payload,claimed):
    request=Request(url,data=json.dumps(payload).encode(),headers={
        'Authorization':'Bearer '+secret,'Content-Type':'application/json','Accept':'application/x-ndjson'})
    total=0;result=None
    try:
        with open_runner(request) as response:
            if 'application/x-ndjson' not in response.headers.get('Content-Type',''):
                raise ValueError('Executor does not support progress streaming')
            while True:
                line=response.readline(20001)
                if not line: break
                total+=len(line)
                if len(line)>20000 or total>128000: raise ValueError('Oversized executor stream')
                message=json.loads(line)
                if message.get('type')=='progress':
                    if result is not None: raise ValueError('Progress after final result')
                    record_progress(claimed,message['event'])
                elif message.get('type')=='result':
                    if result is not None: raise ValueError('Duplicate executor result')
                    result=message['result']
                elif message.get('type')=='error':
                    raise ValueError('Executor did not finish the evaluation')
                else: raise ValueError('Unexpected executor event')
    except HTTPError as exc:
        return {'error_result':{'status':'blocked','retryable':exc.code in {409,429} or exc.code>=500,'result_code':'execution_unavailable',
            'message':'El ejecutor aislado no está disponible. Reintenta más tarde.'}}
    if result is None: raise ValueError('Executor result missing')
    return result


def process_one(item):
    claimed = claim(item)
    if not claimed:
        return
    try:
        # Registered deliveries remain eligible after closure, but removed
        # membership/repository bindings must not be evaluated as valid ownership.
        team = get_item(item["PK"], f"TEAM#{item['team_id']}")
        participant = get_item(item["PK"], f"USER#{item['participant_id']}")
        if not team or team.get("repo_name", "").casefold() != item["repo_name"].casefold() or not participant or participant.get("team_id") != item["team_id"]:
            result = {"status": "blocked", "result_code": "binding_changed", "message": "Tu registro o repositorio vinculado cambió. Consulta con el instructor."}
        else:
            result = execute_plan(claimed) if settings.evaluation_runner_url else inspect_source(item)
    except Exception:
        logger.exception("Preflight failed for evaluation=%s", item["evaluation_id"])
        result = {"status": "blocked", "result_code": "worker_error", "message": "Ocurrió un error al revisar la entrega. Puedes reintentar sin perder puntos."}
    if result.get('retryable'):
        requeue(claimed)
        return
    if claimed.get('operation')=='plan' and result.get('status')=='passed':
        result['message']='Plan válido. Agrega o ejecuta el paso de deploy para desplegar la infraestructura y completar la misión. Esta validación no concede puntos técnicos.'
    saved=finish(claimed, result,score=claimed.get('operation')!='plan')
    if saved and result.get('status')=='passed' and claimed.get('operation')=='deploy':
        try:
            from pathlib import Path
            secret=Path(settings.evaluation_runner_token_file).read_text().strip()
            internal_json(settings.playground_manager_url+'/activate',secret,
                {'event_id':claimed['event_id'],'team_id':claimed['team_id'],'lab_key':result['deployment']['lab_key']},10)
        except Exception:logger.warning('Generation activation deferred to reconciliation')
    if not saved and result.get('status')=='passed':
        finish(claimed,{'status':'blocked','result_code':'authorization_changed',
                       'message':'La autorización o el registro cambió durante la evaluación. Reautoriza y reintenta.'})


def requeue(item):
    try:
        table_resource().update_item(Key={'PK':item['PK'],'SK':item['SK']},
            UpdateExpression='SET #s = :pending, message = :message, updated_at = :updated REMOVE lease_token, lease_expires_at',
            ConditionExpression='#s IN (:preparing, :running) AND lease_token = :token',
            ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':pending':'pending',':preparing':'preparing',':running':'running',
                ':token':item['lease_token'],':message':'Esperando un cupo disponible en el evaluador.',':updated':timestamp()})
    except ClientError as error:
        if error.response['Error']['Code']!='ConditionalCheckFailedException':raise


def runner_available():
    if not settings.evaluation_runner_url:return settings.evaluation_concurrency
    try:
        request=Request(settings.evaluation_runner_url+'/health')
        with build_opener(NoRedirect).open(request,timeout=3) as response:
            status=json.loads(response.read(4096))
        return max(0,min(settings.evaluation_concurrency,int(status.get('available',1)))) if status.get('ready') else 0
    except Exception:
        return 0


def queue_expired(item,now):
    if not item.get('queue_accounted'):return False
    try:return now-datetime.fromisoformat(item['queued_at']).timestamp()>settings.evaluation_queue_wait_seconds
    except (KeyError,ValueError):return False


def tick(executor=None,futures=None):
    futures=[] if futures is None else futures
    for future in list(futures):
        if future.done():
            try:future.result()
            except Exception:logger.exception('Evaluation task failed')
            futures.remove(future)
    rows=scan_items(Attr('type').eq('evaluation') & Attr('status').is_in(['pending','preparing','running']))
    now=int(time.time())
    for item in rows:
        if item.get('status') in {'preparing','running'} and int(item.get('lease_expires_at',now+1))<=now:
            # Recover the queue slot without burning a participant retry.
            requeue(item)
    for item in rows:
        if item.get('status')=='pending' and queue_expired(item,now):
            claimed=claim(item)
            if claimed:finish(claimed,{'status':'blocked','result_code':'queue_timeout','message':'La entrega superó el tiempo máximo en cola. Vuelve a ejecutar el workflow con retry cuando haya cupos.'})
            item['status']='expired'
    credits=min(max(0,settings.evaluation_concurrency-len(futures)),runner_available())
    pending=sorted((item for item in rows if item.get('status')=='pending'),key=queued_order)
    for item in pending[:credits]:
        if executor:futures.append(executor.submit(process_one,item))
        else:process_one(item)


def main():
    logging.basicConfig(level=logging.INFO)
    stopping=False
    def stop(*_args):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    futures=[]
    with ThreadPoolExecutor(max_workers=settings.evaluation_concurrency) as executor:
        while not stopping:
            try:tick(executor,futures)
            except Exception:logger.exception('Evaluation polling failed')
            for _ in range(3):
                if stopping:break
                time.sleep(1)


if __name__ == "__main__":
    main()
