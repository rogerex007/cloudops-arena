"""Advance timed missions independently of browser traffic, with conditional writes."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from .db import scan_items, table_resource
from .gamepack import load_pack

logger=logging.getLogger(__name__)


def advance_due_missions(now=None):
    now=int(time.time()) if now is None else int(now)
    events=scan_items(Attr('type').eq('event') & Attr('status').eq('open') & Attr('mission_deadline').lte(now))
    changed=0
    for event in events:
        if event.get('status')!='open' or event.get('mission_deadline') is None or int(event['mission_deadline'])>now:
            continue
        if event.get('missions_started') is False:continue
        if event.get('mission_sequence_complete') or event.get('auto_advance_missions') is False:
            continue
        try:
            missions=load_pack(event.get('game_pack','aws-event-driven'))['missions']
            index=next((i for i,m in enumerate(missions) if m['id']==event.get('active_mission_id')),None)
            if index is None:continue
            following=missions[index+1] if index+1<len(missions) else None
            values={':open':'open',':active':event['active_mission_id'],':deadline':event['mission_deadline'],
                    ':now':datetime.fromtimestamp(now,timezone.utc).isoformat(),':pack':event.get('game_pack','aws-event-driven'),':false':False}
            condition='#status=:open AND active_mission_id=:active AND mission_deadline=:deadline AND game_pack=:pack AND (attribute_not_exists(auto_advance_missions) OR auto_advance_missions<>:false) AND (attribute_not_exists(mission_sequence_complete) OR mission_sequence_complete=:false)'
            if following:
                seconds=max(1,int(following.get('duration_minutes',15)))*60
                values.update({':next':following['id'],':next_deadline':now+seconds,':seconds':seconds})
                expression='SET active_mission_id=:next, mission_deadline=:next_deadline, mission_remaining=:seconds, updated_at=:now'
            else:
                # Do not finish the event: accepted deliveries can still complete,
                # and the final deployed lab remains available for the wrap-up.
                values.update({':true':True,':zero':0})
                expression='SET mission_sequence_complete=:true, mission_remaining=:zero, updated_at=:now'
            table_resource().update_item(Key={'PK':event['PK'],'SK':'META'},UpdateExpression=expression,
                ConditionExpression=condition,ExpressionAttributeNames={'#status':'status'},ExpressionAttributeValues=values)
            changed+=1
        except ClientError as error:
            if error.response.get('Error',{}).get('Code')!='ConditionalCheckFailedException':
                logger.exception('Mission scheduler database failure')
        except Exception:
            logger.exception('Mission scheduler could not advance an event')
    return changed


@asynccontextmanager
async def mission_scheduler_lifespan(app):
    async def run():
        while True:
            await asyncio.sleep(2)
            try:await asyncio.to_thread(advance_due_missions)
            except Exception:logger.exception('Mission scheduler tick failed; retrying')
    task=asyncio.create_task(run())
    try:yield
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
