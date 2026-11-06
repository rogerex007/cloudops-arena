"""Public projection is opt-in, read-only and excludes private participant data."""
import json
import pytest
from fastapi import HTTPException
from app import main

TOKEN='s'*32

@pytest.fixture
def screen(monkeypatch):
    rows={('EVENT#event','META'):{'title':'Taller','status':'open','game_pack':'pack','active_mission_id':'mission-01'}}
    teams=[{'SK':'TEAM#a','type':'team','name':'Ana','score':20,'email':'private@example.test','repo_url':'private'},
           {'SK':'TEAM#b','type':'team','name':'Beto','score':20},
           {'SK':'TEAM#c','type':'team','name':'Carla','score':10},
           {'SK':'USER#a','type':'participant','name':'Should not appear','score':99}]
    class Table:
        def update_item(self,**kwargs):
            event=rows[(kwargs['Key']['PK'],kwargs['Key']['SK'])]
            if kwargs['UpdateExpression'].startswith('REMOVE'):event.pop('leaderboard_token',None)
            else:event.setdefault('leaderboard_token',TOKEN)
            return {'Attributes':event.copy()}
        def put_item(self,Item):rows[(Item['PK'],Item['SK'])]=Item
        def delete_item(self,Key):rows.pop((Key['PK'],Key['SK']),None)
    monkeypatch.setattr(main,'get_item',lambda pk,sk:rows.get((pk,sk)))
    monkeypatch.setattr(main,'query_partition',lambda pk:teams)
    monkeypatch.setattr(main,'table_resource',lambda:Table())
    monkeypatch.setattr(main,'load_pack',lambda _: {'missions':[{'id':'mission-01','title':'Una misión'}]})
    return rows,teams


def test_screen_must_be_explicitly_shared_and_can_be_revoked(screen):
    with pytest.raises(HTTPException) as error:main.public_leaderboard_screen(TOKEN)
    assert error.value.status_code==404
    assert main.share_leaderboard('event',{})=={'path':'/clasificacion/'+TOKEN}
    assert main.share_leaderboard('event',{})=={'path':'/clasificacion/'+TOKEN}
    assert main.public_leaderboard_screen(TOKEN).status_code==200
    main.revoke_leaderboard('event',{})
    with pytest.raises(HTTPException) as error:main.public_leaderboard_screen(TOKEN)
    assert error.value.status_code==404


def test_public_screen_only_returns_display_names_scores_and_event_summary(screen):
    rows,teams=screen;main.share_leaderboard('event',{})
    response=main.public_leaderboard_screen(TOKEN);data=json.loads(response.body)
    assert response.headers['cache-control']=='no-store'
    assert data['leaderboard']==[{'rank':1,'name':'Ana','score':20},{'rank':2,'name':'Beto','score':20},{'rank':3,'name':'Carla','score':10}]
    assert data['mission']=='Una misión'
    assert 'email' not in response.body.decode() and 'repo_url' not in response.body.decode()
    assert 'team_id' not in response.body.decode() and 'event_id' not in response.body.decode()
    teams[2]['score']=30;rows[('EVENT#event','META')]['status']='finished'
    updated=json.loads(main.public_leaderboard_screen(TOKEN).body)
    assert updated['leaderboard'][0]['name']=='Carla' and updated['status']=='finished'


def test_old_index_cannot_read_event_after_token_changes(screen):
    rows,_=screen;main.share_leaderboard('event',{})
    rows[('EVENT#event','META')]['leaderboard_token']='n'*32
    with pytest.raises(HTTPException):main.public_leaderboard_screen(TOKEN)


@pytest.mark.parametrize('token',['event','../admin','s'*200])
def test_invalid_screen_token_is_rejected_without_database_lookup(monkeypatch,token):
    monkeypatch.setattr(main,'get_item',lambda *args:pytest.fail('Invalid token queried the database'))
    with pytest.raises(HTTPException) as error:main.public_leaderboard_screen(token)
    assert error.value.status_code==404


def test_public_and_participant_views_use_same_response_tiebreak(screen):
    _,teams=screen
    for t in teams:
        if t['type']=='team':t['team_id']=t['SK'][5:]
    teams.extend([
        {'type':'submission','team_id':'a','status':'passed','points':20,'created_at':'2026-11-06T10:02:00Z'},
        {'type':'submission','team_id':'b','status':'passed','points':20,'created_at':'2026-11-06T10:01:00Z'},
    ])
    main.share_leaderboard('event',{})
    public=json.loads(main.public_leaderboard_screen(TOKEN).body)['leaderboard']
    private=main.leaderboard({'event_id':'event','team_id':'b'})['leaderboard']
    assert [r['name'] for r in public]==[r['name'] for r in private]==['Beto','Ana','Carla']
    assert [r['rank'] for r in public]==[1,2,3]
