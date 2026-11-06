"""Authenticated inventory proxy. Lab identity comes only from membership."""
import hashlib
import hmac
import json
from pathlib import Path
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, Header, HTTPException

from .config import settings
from .db import get_item
from .security import require_participant

router = APIRouter()


@router.get('/internal/playgrounds/events/{event_id}')
def event_state(event_id: str, authorization: str = Header(default='')):
    secret = Path(settings.evaluation_runner_token_file).read_text().strip() if settings.evaluation_runner_token_file else ''
    if not secret or not hmac.compare_digest(authorization, 'Bearer '+secret):
        raise HTTPException(401, 'Unauthorized')
    event = get_item('EVENT#'+event_id, 'META')
    return {'status': event.get('status') if event else 'finished'}


@router.get('/internal/playgrounds/owners/{event_id}/{team_id}')
def owner_receipt(event_id:str,team_id:str,authorization:str=Header(default='')):
    secret=Path(settings.evaluation_runner_token_file).read_text().strip() if settings.evaluation_runner_token_file else ''
    if not secret or not hmac.compare_digest(authorization,'Bearer '+secret):raise HTTPException(401,'Unauthorized')
    event=get_item('EVENT#'+event_id,'META')
    return {'status':event.get('status') if event else 'finished','receipt':get_item('EVENT#'+event_id,'DEPLOY#'+team_id)}


def control(path, body=None):
    if not settings.playground_manager_url:
        raise HTTPException(503, 'Los playgrounds aún no están habilitados en este despliegue.')
    try:
        token = Path(settings.evaluation_runner_token_file).read_text().strip()
        request = urllib.request.Request(settings.playground_manager_url.rstrip('/')+path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read(64*1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 429: raise HTTPException(429, 'Se alcanzó el cupo de playgrounds. Contacta al instructor.') from exc
        raise HTTPException(503, 'El gestor de playgrounds no está disponible. Reintenta en unos segundos.') from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'El gestor de playgrounds no está disponible. Reintenta en unos segundos.') from exc


def identity(principal, *, write=False):
    event_id, team_id = principal['event_id'], principal['team_id']
    pk = 'EVENT#'+event_id
    user = get_item(pk, 'USER#'+principal['sub'])
    event = get_item(pk, 'META')
    team = get_item(pk, 'TEAM#'+team_id)
    if not user or user.get('team_id') != team_id or not team or not event:
        raise HTTPException(403, 'Tu registro en este evento ya no está disponible.')
    if event.get('status') == 'finished':
        raise HTTPException(403, 'El evento finalizó. Tu playground ya no está disponible.')
    if write and event.get('status') != 'open':
        raise HTTPException(409, 'El evento está pausado. Puedes consultar la última captura.')
    return hashlib.sha256(json.dumps([event_id, team_id], separators=(',', ':')).encode()).hexdigest()


@router.get('/api/v1/participant/playground')
def read_playground(principal: dict = Depends(require_participant)):
    identity(principal)
    if not settings.playground_manager_url:
        return {'status': 'disabled', 'message': 'El instructor aún no ha habilitado los playgrounds.'}
    pk='EVENT#'+principal['event_id']
    receipt=get_item(pk,'DEPLOY#'+principal['team_id'])
    if receipt and receipt.get('status')=='applied' and receipt.get('validator')=='aws-event-driven-deploy-v1':
        lab=control('/labs/'+receipt['lab_key'])
        provenance=lab.get('deployment') or {}
        if all(provenance.get(key)==receipt.get(key) for key in ('evaluation_id','commit_sha','source_digest','lab_key')):
            return {**lab,'deployment':{key:receipt[key] for key in ('evaluation_id','commit_sha','source_digest')},
                'repo_name':receipt['repo_name'],'message':lab.get('message','Laboratorio finalizado.') if lab.get('status')=='expired' else 'Infraestructura desplegada desde tu commit verificado.'}
    return {
        'status': 'awaiting_deployment', 'snapshot': None,
        'message': 'Aún no hay infraestructura desplegada desde tu repositorio. En la misión 02, agrega el paso de despliegue a tu workflow de GitHub Actions.',
    }


@router.post('/api/v1/participant/playground')
def prepare_playground(principal: dict = Depends(require_participant)):
    identity(principal, write=True)
    raise HTTPException(409, 'Los despliegues se solicitan únicamente desde el paso de deploy de GitHub Actions, con el commit verificado.')
