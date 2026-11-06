"""Authenticated SSE snapshots with curated progress, not raw Terraform output."""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from .db import table_resource, get_item
from .evaluations import public_evaluation
from .security import require_participant

router=APIRouter()
TERMINAL={'passed','failed','blocked'}


def read_evaluation(event_id,evaluation_id):
    return table_resource().get_item(Key={'PK':f'EVENT#{event_id}','SK':f'EVAL#{evaluation_id}'},ConsistentRead=True).get('Item')


@router.get('/api/v1/participant/evaluations/{evaluation_id}/events')
async def events(evaluation_id:str,request:Request,principal:dict=Depends(require_participant)):
    membership=await asyncio.to_thread(get_item,f"EVENT#{principal['event_id']}",f"USER#{principal['sub']}")
    if not membership or membership.get('team_id')!=principal['team_id']:
        raise HTTPException(403,'Tu registro ya no está disponible.')
    first=await asyncio.to_thread(read_evaluation,principal['event_id'],evaluation_id)
    if not first or first.get('team_id')!=principal['team_id']:
        raise HTTPException(404,'Entrega no encontrada.')
    async def stream():
        previous=None
        started=time.monotonic()
        heartbeat=started
        while time.monotonic()-started<55:
            if await request.is_disconnected(): return
            item=await asyncio.to_thread(read_evaluation,principal['event_id'],evaluation_id)
            if not item or item.get('team_id')!=principal['team_id']: return
            payload=json.dumps(jsonable_encoder(public_evaluation(item)),ensure_ascii=False,separators=(',',':'))
            if payload!=previous:
                yield 'event: evaluation\ndata: '+payload+'\n\n'
                previous=payload
                heartbeat=time.monotonic()
            if item['status'] in TERMINAL: return
            if time.monotonic()-heartbeat>10:
                yield ': keepalive\n\n';heartbeat=time.monotonic()
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={
        'Cache-Control':'private, no-store','X-Accel-Buffering':'no',
    })
