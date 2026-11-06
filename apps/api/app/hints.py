"""Earned coins derive from unique completions; spending is atomic and auditable."""
import time
from boto3.dynamodb.types import TypeSerializer
from fastapi import APIRouter,Depends,HTTPException
from .db import get_item,query_partition,dynamodb_client
from .gamepack import load_pack,get_mission
from .security import require_participant
from .mission_clock import require_time,deadline_condition

router=APIRouter()


def wallet(pack,rows,team):
    done={row.get('mission_id') for row in rows if row.get('type')=='submission' and row.get('team_id')==team and row.get('status')=='passed' and row.get('source')!='demo'}
    earned=sum(int(mission.get('coin_reward',10)) for mission in pack.get('missions',[]) if mission['id'] in done)
    spent=int(next((row.get('spent',0) for row in rows if row.get('SK')=='WALLET#'+team),0))
    return {'earned':earned,'spent':spent,'balance':max(0,earned-spent)}


def catalog(pack,rows,team):
    purchased={(row.get('mission_id'),row.get('hint_id')) for row in rows if row.get('type')=='hint-purchase' and row.get('team_id')==team}
    return {mission['id']:[{'id':hint['id'],'title':hint['title'],'cost':int(hint['cost']),
        'purchased':(mission['id'],hint['id']) in purchased,**({'content':hint['content']} if (mission['id'],hint['id']) in purchased else {})}
        for hint in mission.get('hints',[])] for mission in pack.get('missions',[])}


@router.post('/api/v1/participant/missions/{mission_id}/hints/{hint_id}')
def buy_hint(mission_id:str,hint_id:str,principal:dict=Depends(require_participant)):
    pk='EVENT#'+principal['event_id'];team=principal['team_id']
    member=get_item(pk,'USER#'+principal['sub']);event=get_item(pk,'META')
    if not member or member.get('team_id')!=team or not get_item(pk,'TEAM#'+team):raise HTTPException(403,'Tu registro ya no está disponible.')
    if not event or event.get('status')!='open':raise HTTPException(409,'El evento no está abierto.')
    require_time(event)
    if event.get('active_mission_id')!=mission_id:raise HTTPException(409,'Esta misión no está activa.')
    pack=load_pack(event.get('game_pack','aws-event-driven'));mission=get_mission(pack,mission_id)
    hint=next((hint for hint in (mission or {}).get('hints',[]) if hint['id']==hint_id),None)
    if not hint:raise HTTPException(404,'Esta pista no existe.')
    rows=query_partition(pk);owned=catalog(pack,rows,team).get(mission_id,[])
    existing=next((entry for entry in owned if entry['id']==hint_id and entry['purchased']),None)
    if existing:return {'hint':existing,'wallet':wallet(pack,rows,team),'already_purchased':True}
    funds=wallet(pack,rows,team);cost=int(hint['cost'])
    if cost<1 or funds['balance']<cost:raise HTTPException(409,'No tienes suficientes monedas. Completa otra misión para ganar más.')
    serialize=lambda value:{key:TypeSerializer().serialize(item) for key,item in value.items()}
    key=lambda sk:serialize({'PK':pk,'SK':sk})
    purchase={'PK':pk,'SK':f'HINT#{team}#{mission_id}#{hint_id}','type':'hint-purchase','team_id':team,
              'mission_id':mission_id,'hint_id':hint_id,'cost':cost,'purchased_at':int(time.time()),'pack_version':str(pack['version'])}
    client=dynamodb_client()
    try:
        client.transact_write_items(TransactItems=[
            {'Put':{'TableName':client_table(),'Item':serialize(purchase),'ConditionExpression':'attribute_not_exists(PK)'}},
            {'Update':{'TableName':client_table(),'Key':key('WALLET#'+team),
                'UpdateExpression':'SET spent = :next',
                'ConditionExpression':('(attribute_not_exists(spent) OR spent = :previous)' if funds['spent']==0 else 'spent = :previous'),
                'ExpressionAttributeValues':serialize({':next':funds['spent']+cost,':previous':funds['spent']})}},
            {'ConditionCheck':{'TableName':client_table(),'Key':key('META'),
                'ConditionExpression':'#s = :open AND active_mission_id = :mission AND '+deadline_condition(),
                'ExpressionAttributeNames':{'#s':'status'},'ExpressionAttributeValues':serialize({':open':'open',':mission':mission_id,':clock_now':int(time.time())})}},
            {'ConditionCheck':{'TableName':client_table(),'Key':key('USER#'+principal['sub']),
                'ConditionExpression':'team_id = :team','ExpressionAttributeValues':serialize({':team':team})}},
            {'ConditionCheck':{'TableName':client_table(),'Key':key('TEAM#'+team),'ConditionExpression':'attribute_exists(PK)'}},
        ])
    except client.exceptions.TransactionCanceledException:
        purchased=get_item(pk,purchase['SK'])
        if purchased:return {'hint':{'id':hint_id,'title':hint['title'],'content':hint['content'],'cost':cost,'purchased':True},'already_purchased':True}
        raise HTTPException(409,'Cambió el saldo o terminó la misión. Actualiza e inténtalo de nuevo.')
    return {'hint':{'id':hint_id,'title':hint['title'],'content':hint['content'],'cost':cost,'purchased':True},
            'wallet':{**funds,'spent':funds['spent']+cost,'balance':funds['balance']-cost},'already_purchased':False}


def client_table():
    from .config import settings
    return settings.dynamodb_table_name
