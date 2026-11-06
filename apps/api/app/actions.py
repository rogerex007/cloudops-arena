"""GitHub Actions may request/read evaluations; only our judge can grade them."""
import hashlib
import re

import jwt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .db import get_item, query_partition, table_resource
from .evaluations import EvaluationRequest, public_evaluation, register_evaluation, queue_summary
from .gamepack import get_mission, load_pack
from .github_app import GitHubError, api, installation_token

router=APIRouter()
ISSUER='https://token.actions.githubusercontent.com'
KEYS=jwt.PyJWKClient(ISSUER+'/.well-known/jwks',timeout=5,cache_jwk_set=True,lifespan=300)


def verify_token(authorization):
    if not authorization or not authorization.startswith('Bearer ') or len(authorization)>20000:
        raise HTTPException(401,'Se requiere una identidad OIDC de GitHub Actions.')
    token=authorization[7:]
    try:
        if jwt.get_unverified_header(token).get('alg')!='RS256':
            raise jwt.InvalidTokenError()
        key=KEYS.get_signing_key_from_jwt(token).key
        claims=jwt.decode(token,key,algorithms=['RS256'],audience=settings.actions_oidc_audience,
            issuer=ISSUER,leeway=15,options={'require':['iss','aud','sub','iat','exp','nbf','jti',
                'repository','repository_id','repository_owner_id','sha','ref','event_name','workflow_ref','run_id','run_attempt']})
        if claims['exp']-claims['iat']>600 or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',claims['repository']):
            raise jwt.InvalidTokenError()
        if not re.fullmatch(r'[a-f0-9]{40}',claims['sha']) or claims['event_name'] not in {'push','workflow_dispatch'}:
            raise jwt.InvalidTokenError()
        if not all(str(claims[field]).isdigit() for field in ('repository_id','repository_owner_id','run_id','run_attempt')):
            raise jwt.InvalidTokenError()
        if not isinstance(claims['jti'],str) or not 1<=len(claims['jti'])<=256:
            raise jwt.InvalidTokenError()
        return claims
    except (jwt.PyJWTError,ValueError,TypeError,KeyError):
        raise HTTPException(401,'La identidad de GitHub Actions no es válida o venció.')


def binding(event_id,mission_id,claims,*,refresh=False,accepted_ref=None):
    pk=f'EVENT#{event_id}'
    event=get_item(pk,'META')
    if not event: raise HTTPException(403,'Este evento no autoriza el repositorio.')
    proof=next((row for row in query_partition(pk) if row.get('type')=='github-authorization'
        and str(row.get('repository_id'))==str(claims['repository_id'])
        and str(row.get('github_user_id'))==str(claims['repository_owner_id'])
        and row.get('repo_name','').casefold()==claims['repository'].casefold()),None)
    if not proof: raise HTTPException(403,'Autoriza primero este repositorio desde el portal de Arena.')
    team=get_item(pk,f"TEAM#{proof['team_id']}")
    participant=get_item(pk,f"USER#{proof['participant_id']}")
    if not team or team.get('repo_name','').casefold()!=claims['repository'].casefold() or not participant or participant.get('team_id')!=proof['team_id']:
        raise HTTPException(403,'La vinculación del repositorio o el participante cambió.')
    branch=proof.get('default_branch','main')
    if refresh:
        try:
            token=installation_token(proof)
            repo=api('/repos/'+proof['repo_name'],token=token)
        except GitHubError:
            raise HTTPException(403,'GitHub no confirmó el acceso de la App al repositorio.')
        if str(repo.get('id'))!=str(proof['repository_id']) or str(repo.get('owner',{}).get('id'))!=str(proof['github_user_id']) or repo.get('full_name','').casefold()!=proof['repo_name'].casefold():
            raise HTTPException(403,'El repositorio autorizado cambió.')
        branch=repo['default_branch']
    expected_ref=accepted_ref or f'refs/heads/{branch}'
    mission=get_mission(load_pack(event.get('game_pack','aws-event-driven')),mission_id)
    if not mission or not mission.get('workflow'):
        raise HTTPException(403,'Esta misión no admite solicitudes desde Actions.')
    expected_workflow=f"{proof['repo_name']}/{mission['workflow']}@{expected_ref}"
    workflow_ref=claims['workflow_ref']
    repo_prefix=proof['repo_name']+'/'
    workflow_matches=(isinstance(workflow_ref,str) and workflow_ref[:len(repo_prefix)].casefold()==repo_prefix.casefold()
        and workflow_ref[len(repo_prefix):]==expected_workflow[len(repo_prefix):])
    if claims['ref']!=expected_ref or not workflow_matches:
        raise HTTPException(403,'Usa el workflow de la misión en la rama predeterminada del repositorio.')
    return event,proof,{'event_id':event_id,'team_id':proof['team_id'],'sub':proof['participant_id'],'role':'participant'}


class ActionsRequest(BaseModel):
    event_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    mission_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    retry:bool=False
    operation:str=Field(default='plan',pattern=r'^(plan|deploy)$')


@router.post('/api/v1/actions/evaluations')
def submit(body:ActionsRequest,authorization:str|None=Header(default=None)):
    claims=verify_token(authorization)
    event,proof,principal=binding(body.event_id,body.mission_id,claims,refresh=True)
    if event.get('status')!='open': raise HTTPException(403,'El evento no está aceptando entregas.')
    if event.get('active_mission_id')!=body.mission_id: raise HTTPException(409,'La misión no está activa.')
    table=table_resource()
    try:
        table.put_item(Item={'PK':'OIDCREPLAY#'+hashlib.sha256(claims['jti'].encode()).hexdigest(),
            'SK':'TOKEN','type':'actions-oidc-use','expires_at':int(claims['exp']),
            'event_id':body.event_id,'repository_id':str(claims['repository_id'])},
            ConditionExpression='attribute_not_exists(PK)')
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise HTTPException(409,'Esta identidad OIDC ya se utilizó. Solicita un token nuevo.')
    pk=f'EVENT#{body.event_id}'
    if body.operation=='deploy' and body.mission_id!='mission-02':
        raise HTTPException(422,'El despliegue de infraestructura corresponde a la misión 02.')
    if get_item(pk,f"SUB#{proof['team_id']}#{body.mission_id}") and body.operation!='deploy':
        return {'already_completed':True,'status':'passed','points_awarded':0,'message':'La misión ya fue aprobada. No se ejecutó otra evaluación.'}
    provenance={'source':'github-actions','actions_run_id':str(claims['run_id']),
        'actions_run_attempt':str(claims['run_attempt']),'actions_ref':claims['ref'],
        'actions_actor_id':str(claims.get('actor_id','')),
        'actions_url':f"https://github.com/{claims['repository']}/actions/runs/{claims['run_id']}"}
    if body.mission_id=='mission-02':provenance['operation']=body.operation
    return register_evaluation(body.mission_id,EvaluationRequest(commit_sha=claims['sha'],retry=body.retry),principal,provenance)


@router.get('/api/v1/actions/evaluations/{event_id}/{evaluation_id}')
def status(event_id:str,evaluation_id:str,authorization:str|None=Header(default=None)):
    claims=verify_token(authorization)
    item=get_item(f'EVENT#{event_id}',f'EVAL#{evaluation_id}')
    if not item: raise HTTPException(404,'Entrega no encontrada.')
    _event,proof,_principal=binding(event_id,item['mission_id'],claims,accepted_ref=item.get('actions_ref'))
    if item['team_id']!=proof['team_id'] or item['repo_name'].casefold()!=claims['repository'].casefold():
        raise HTTPException(403,'La entrega no pertenece a este repositorio.')
    queue=queue_summary(query_partition(f'EVENT#{event_id}')) if item.get('status')=='pending' else None
    return {'evaluation':public_evaluation(item,queue)}
