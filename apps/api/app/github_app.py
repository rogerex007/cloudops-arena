"""Repository ownership authorization and bounded, authenticated source reads."""
import base64
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeSerializer
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .config import settings
from .db import dynamodb_client, get_item, table_resource
from .gamepack import get_mission, load_pack
from .security import require_participant

router=APIRouter()
CALLBACK='/api/v1/github/callback'


class GitHubError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):
        return None


def credentials():
    try:
        config=json.loads(Path(settings.github_app_config_file).read_text())
        if not all(config.get(key) for key in ('app_id','client_id','client_secret','slug')):
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9-]+',config['slug']):
            raise ValueError()
        key=Path(settings.github_app_private_key_file).read_text()
        if 'PRIVATE KEY' not in key:
            raise ValueError()
        return config,key
    except (ValueError,OSError,TypeError):
        raise GitHubError('El instructor debe configurar la GitHub App antes de autorizar repositorios.')


def api(path, *, token=None, body=None, method=None, basic=None, oauth=False):
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Invalid GitHub path')
    headers={'Accept':'application/json' if oauth else 'application/vnd.github+json',
             'User-Agent':'CloudOpsArena','X-GitHub-Api-Version':'2022-11-28'}
    if token:
        headers['Authorization']='Bearer '+token
    if basic:
        headers['Authorization']='Basic '+base64.b64encode(basic.encode()).decode()
    data=None
    if body is not None:
        data=(urlencode(body).encode() if oauth else json.dumps(body).encode())
        headers['Content-Type']='application/x-www-form-urlencoded' if oauth else 'application/json'
    host='https://github.com' if oauth else 'https://api.github.com'
    try:
        with build_opener(NoRedirect).open(Request(host+path,data=data,headers=headers,method=method),timeout=15) as response:
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:
            raise ValueError()
        result=json.loads(raw) if raw else {}
        if not isinstance(result,dict) or result.get('error'):
            raise ValueError()
        return result
    except (HTTPError,URLError,OSError,ValueError):
        raise GitHubError('GitHub no permitió verificar el acceso. Revisa la instalación, los permisos y el repositorio, o reintenta más tarde.')


def app_token(config,key):
    now=int(time.time())
    return jwt.encode({'iat':now-30,'exp':now+480,'iss':str(config['app_id'])},key,algorithm='RS256')


def installation_token(authorization):
    config,key=credentials()
    installation_id=int(authorization['installation_id'])
    app=app_token(config,key)
    installation=api(f'/app/installations/{installation_id}',token=app)
    if installation.get('suspended_at') or installation.get('account',{}).get('id')!=int(authorization['github_user_id']):
        raise GitHubError('La instalación de GitHub cambió o está suspendida. Autoriza el repositorio nuevamente.')
    result=api(f'/app/installations/{installation_id}/access_tokens',token=app,body={
        'repository_ids':[int(authorization['repository_id'])], 'permissions':{'contents':'read'},
    })
    return result['token']


def connection_status(team,rows):
    try:
        config,_=credentials()
        available=True
    except GitHubError:
        config={}; available=False
    authorization=next((row for row in rows if row.get('SK')==f"GHAUTH#{team['team_id']}"),{})
    verified=available and authorization.get('repo_name','').casefold()==team.get('repo_name','').casefold() and bool(authorization.get('repository_id'))
    return {'available':available,'authorized':verified,'login':authorization.get('github_login','') if verified else '',
            'install_url':f"https://github.com/apps/{config['slug']}/installations/new" if available else ''}


@router.post('/api/v1/participant/github/authorize')
def authorize(principal:dict=Depends(require_participant)):
    try: config,_=credentials()
    except GitHubError as exc: raise HTTPException(503,str(exc))
    pk=f"EVENT#{principal['event_id']}"
    event=get_item(pk,'META')
    team=get_item(pk,f"TEAM#{principal['team_id']}")
    participant=get_item(pk,f"USER#{principal['sub']}")
    if not event or event.get('status')!='open' or not team or not participant or participant.get('team_id')!=principal['team_id']:
        raise HTTPException(403,'Tu evento o registro no permite autorizar repositorios en este momento.')
    repo=team.get('repo_name','')
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo):
        raise HTTPException(409,'Primero vincula un repositorio de GitHub.')
    state=secrets.token_urlsafe(32)
    verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    table_resource().put_item(Item={
        'PK':'GHSTATE#'+hashlib.sha256(state.encode()).hexdigest(),'SK':'AUTH','type':'github-oauth-state',
        'event_id':principal['event_id'],'team_id':principal['team_id'],'participant_id':principal['sub'],
        'repo_name':repo,'verifier':verifier,'expires_at':int(time.time())+600,
    },ConditionExpression='attribute_not_exists(PK)')
    query=urlencode({'client_id':config['client_id'],'redirect_uri':settings.public_base_url+CALLBACK,
                     'state':state,'code_challenge':challenge,'code_challenge_method':'S256'})
    return {'url':'https://github.com/login/oauth/authorize?'+query}


@router.get(CALLBACK)
def callback(state:str='',code:str='',error:str=''):
    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',state) or not code or len(code)>256 or error:
        return RedirectResponse(settings.public_base_url+'/?github=error',status_code=303,headers=headers)
    key={'PK':'GHSTATE#'+hashlib.sha256(state.encode()).hexdigest(),'SK':'AUTH'}
    table=table_resource()
    row=table.get_item(Key=key,ConsistentRead=True).get('Item')
    if not row or int(row.get('expires_at',0))<=int(time.time()):
        raise HTTPException(400,'El enlace de autorización venció o ya se utilizó. Vuelve a Arena y reintenta.')
    try:
        table.delete_item(Key=key,ConditionExpression='expires_at > :now',ExpressionAttributeValues={':now':int(time.time())})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise HTTPException(400,'El enlace de autorización ya se utilizó.')
    token=None; config=None
    try:
        config,pem=credentials()
        result=api('/login/oauth/access_token',oauth=True,body={
            'client_id':config['client_id'],'client_secret':config['client_secret'],'code':code,
            'redirect_uri':settings.public_base_url+CALLBACK,'code_verifier':row['verifier'],
        })
        token=result['access_token']
        user=api('/user',token=token)
        repo=api('/repos/'+row['repo_name'],token=token)
        if repo.get('owner',{}).get('id')!=user.get('id') or repo.get('full_name','').casefold()!=row['repo_name'].casefold():
            raise GitHubError('Autoriza con la cuenta personal propietaria del repositorio vinculado.')
        installation=api('/repos/'+row['repo_name']+'/installation',token=app_token(config,pem))
        if installation.get('account',{}).get('id')!=user['id'] or installation.get('suspended_at'):
            raise GitHubError('Instala la App en la cuenta propietaria y selecciona este repositorio.')
        proof={'PK':f"EVENT#{row['event_id']}",'SK':f"GHAUTH#{row['team_id']}",'type':'github-authorization',
               'team_id':row['team_id'],'participant_id':row['participant_id'],'repo_name':repo['full_name'],
               'repository_id':repo['id'],'github_user_id':user['id'],'github_login':user['login'],
               'installation_id':installation['id'],'verified_at':int(time.time())}
        proof['default_branch']=repo.get('default_branch','main')
        operations=[]
        for sk,expression,values in [
            ('META','#s = :open',{':open':'open'}),
            (f"USER#{row['participant_id']}",'team_id = :team',{':team':row['team_id']}),
            (f"TEAM#{row['team_id']}",'repo_name = :repo',{':repo':row['repo_name']}),
        ]:
            check={'TableName':settings.dynamodb_table_name,'Key':{'PK':{'S':proof['PK']},'SK':{'S':sk}},
                   'ConditionExpression':expression,'ExpressionAttributeValues':{k:TypeSerializer().serialize(v) for k,v in values.items()}}
            if sk=='META': check['ExpressionAttributeNames']={'#s':'status'}
            operations.append({'ConditionCheck':check})
        operations.append({'Put':{'TableName':settings.dynamodb_table_name,'Item':{k:TypeSerializer().serialize(v) for k,v in proof.items()}}})
        dynamodb_client().transact_write_items(TransactItems=operations)
        return RedirectResponse(settings.public_base_url+'/?github=connected',status_code=303,headers=headers)
    except (GitHubError,KeyError,ClientError):
        return RedirectResponse(settings.public_base_url+'/?github=error',status_code=303,headers=headers)
    finally:
        if token and config:
            try: api(f"/applications/{config['client_id']}/token",method='DELETE',basic=config['client_id']+':'+config['client_secret'],body={'access_token':token})
            except GitHubError: pass


def verified_source(item):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',item.get('repo_name','')) or not re.fullmatch(r'[a-f0-9]{40}',item.get('commit_sha','')):
        raise GitHubError('Repositorio o commit inválido.')
    authorization=get_item(item['PK'],f"GHAUTH#{item['team_id']}")
    if not authorization or authorization.get('repo_name','').casefold()!=item['repo_name'].casefold():
        raise GitHubError('Instala la GitHub App y autoriza el repositorio desde Arena antes de evaluar Terraform.')
    owner=get_item(item['PK'],f"USER#{authorization['participant_id']}")
    if not owner or owner.get('team_id')!=item['team_id']:
        raise GitHubError('La persona que autorizó este repositorio ya no pertenece al registro.')
    token=installation_token(authorization)
    repo=api('/repos/'+item['repo_name'],token=token)
    if repo.get('id')!=int(authorization['repository_id']) or repo.get('owner',{}).get('id')!=int(authorization['github_user_id']) or repo.get('full_name','').casefold()!=item['repo_name'].casefold():
        raise GitHubError('El repositorio cambió de nombre o propietario. Autorízalo nuevamente.')
    sha=item['commit_sha']
    commit=api(f"/repos/{item['repo_name']}/git/commits/{sha}",token=token)
    if commit.get('sha')!=sha:
        raise GitHubError('GitHub no confirmó el commit exacto de la entrega.')
    tree_sha=commit.get('tree',{}).get('sha','')
    if not re.fullmatch(r'[a-f0-9]{40}',tree_sha): raise GitHubError('Árbol de archivos inválido.')
    tree=api(f"/repos/{item['repo_name']}/git/trees/{tree_sha}?recursive=1",token=token)
    if tree.get('truncated') or tree.get('sha')!=tree_sha: raise GitHubError('El árbol de archivos está incompleto.')
    pack=load_pack(item['game_pack'])
    mission=get_mission(pack,item['mission_id'])
    if str(pack['version'])!=str(item['pack_version']) or not mission:
        raise GitHubError('La versión del reto cambió.')
    policy=mission.get('evaluation',{})
    paths=policy.get('source_files',[])
    if not paths or len(paths)>30:
        raise GitHubError('La misión no tiene un validador de ejecución configurado.')
    entries={entry['path']:entry for entry in tree.get('tree',[]) if entry.get('type')=='blob' and entry.get('mode') in {'100644','100755'}}
    missing=sorted(set(policy.get('required_files',[])+paths)-set(entries))
    if missing:
        raise HTTPException(422,{'status':'failed','result_code':'missing_files','message':'Faltan archivos en este commit.','missing_files':missing[:20]})
    files={}; total=0
    for path in paths:
        entry=entries[path]
        blob_sha=entry['sha']
        if not re.fullmatch(r'[a-f0-9]{40}',blob_sha) or entry.get('size',0)>256*1024:
            raise GitHubError('El archivo supera los límites del laboratorio.')
        blob=api(f"/repos/{item['repo_name']}/git/blobs/{blob_sha}",token=token)
        if blob.get('encoding')!='base64': raise GitHubError('Contenido no admitido.')
        data=base64.b64decode(blob['content'])
        total+=len(data)
        if len(data)>256*1024 or total>2*1024*1024 or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=blob_sha:
            raise GitHubError('No pudimos verificar el contenido de los archivos.')
        files[path]=base64.b64encode(data).decode()
    validator=policy.get('deployment_validator') if item.get('operation')=='deploy' else policy['validator']
    if not validator:raise GitHubError('El despliegue no está habilitado para esta misión.')
    return {'validator':validator,'files':files,'repository_id':int(repo['id']),
            'installation_id':int(authorization['installation_id']),
            'authorized_participant_id':authorization['participant_id'],
            'github_login':authorization['github_login'],'repository_verified':True}


class SourceRequest(BaseModel):
    lease_token:str=Field(pattern=r'^[a-f0-9]{32}$')


@router.post('/internal/evaluations/{event_id}/{evaluation_id}/source')
def internal_source(event_id:str,evaluation_id:str,body:SourceRequest,authorization:str|None=Header(default=None)):
    try: secret=Path(settings.evaluation_runner_token_file).read_text().strip()
    except OSError: secret=''
    if not secret or not secrets.compare_digest(authorization or '','Bearer '+secret):
        raise HTTPException(401,'Worker authentication required')
    item=get_item(f'EVENT#{event_id}',f'EVAL#{evaluation_id}')
    if not item or item.get('status') not in {'preparing','running'} or item.get('lease_token')!=body.lease_token or int(item.get('lease_expires_at',0))<=int(time.time()):
        raise HTTPException(409,'Evaluation lease is no longer valid')
    try: return verified_source(item)
    except GitHubError as exc: raise HTTPException(503,str(exc))
