import time
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from app import hints
from app.gamepack import public_missions
from app.mission_clock import clock,require_time


def test_deadline_closes_at_zero_and_legacy_events_remain_untimed():
    assert clock({'status':'open','mission_deadline':100},99)['remaining_seconds']==1
    assert clock({'status':'open','mission_deadline':100},100)['closed']
    assert clock({'status':'open'},100)['remaining_seconds'] is None
    assert not clock({'status':'open'},100)['closed']


def test_paused_clock_preserves_remaining_time():
    event={'status':'paused','mission_deadline':100,'mission_remaining':12}
    assert clock(event,1000)['remaining_seconds']==12
    assert not clock(event,1000)['closed']


def test_server_rejects_expired_mission():
    with pytest.raises(HTTPException) as error:require_time({'status':'open','mission_deadline':int(time.time())})
    assert error.value.status_code==410


def pack():
    return {'id':'pack','version':'1','missions':[{'id':'first','coin_reward':10},
        {'id':'second','hints':[{'id':'one','title':'Clue','cost':3,'content':'Private content'}]}]}


def test_wallet_uses_unique_verified_missions_not_repo_link_or_demo():
    rows=[{'type':'submission','team_id':'team','status':'passed','mission_id':'first','source':'quiz'}]*2
    rows += [{'type':'submission','team_id':'team','status':'passed','mission_id':'mission-02-repo'},
        {'type':'submission','team_id':'other','status':'passed','mission_id':'second'},
        {'SK':'WALLET#team','spent':3}]
    assert hints.wallet(pack(),rows,'team')=={'earned':10,'spent':3,'balance':7}
    assert hints.wallet(pack(),[{**rows[0],'source':'demo'}],'team')['earned']==0


def test_hint_text_is_not_public_until_that_mission_hint_is_purchased():
    assert 'hints' not in public_missions(pack())[1]
    rows=[{'type':'hint-purchase','team_id':'team','mission_id':'first','hint_id':'one'}]
    assert 'content' not in hints.catalog(pack(),rows,'team')['second'][0]
    rows[0]['mission_id']='second'
    assert hints.catalog(pack(),rows,'team')['second'][0]['content']=='Private content'
    assert 'content' not in hints.catalog(pack(),rows,'other')['second'][0]


@pytest.fixture
def shop(monkeypatch):
    rows=[{'type':'submission','team_id':'team','status':'passed','mission_id':'first','source':'quiz'}]
    records={'META':{'status':'open','active_mission_id':'second','game_pack':'pack'},'USER#user':{'team_id':'team'},'TEAM#team':{'team_id':'team'}}
    monkeypatch.setattr(hints,'get_item',lambda pk,sk:records.get(sk))
    monkeypatch.setattr(hints,'query_partition',lambda pk:rows)
    monkeypatch.setattr(hints,'load_pack',lambda _id:pack())
    client=Mock();monkeypatch.setattr(hints,'dynamodb_client',lambda:client)
    return records,rows,client,{'event_id':'event','team_id':'team','sub':'user'}


def test_purchase_debits_once_and_returns_owned_hint(shop):
    records,rows,client,principal=shop
    result=hints.buy_hint('second','one',principal)
    assert result['wallet']['balance']==7
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(operations)==5
    assert operations[0]['Put']['ConditionExpression']=='attribute_not_exists(PK)'
    assert operations[1]['Update']['ExpressionAttributeValues'][':next']=={'N':'3'}
    rows.append({'type':'hint-purchase','team_id':'team','mission_id':'second','hint_id':'one'})
    assert hints.buy_hint('second','one',principal)['already_purchased']
    assert client.transact_write_items.call_count==1


@pytest.mark.parametrize('scenario',['no-funds','expired','revoked','paused'])
def test_purchase_denied_without_spending(shop,scenario):
    records,rows,client,principal=shop
    if scenario=='no-funds':rows.clear()
    elif scenario=='expired':records['META']['mission_deadline']=int(time.time())-1
    elif scenario=='revoked':records['USER#user']['team_id']='other'
    else:records['META']['status']='paused'
    with pytest.raises(HTTPException):hints.buy_hint('second','one',principal)
    client.transact_write_items.assert_not_called()
