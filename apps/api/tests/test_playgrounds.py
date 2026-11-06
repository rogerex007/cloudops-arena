import pytest
from fastapi.testclient import TestClient
from app import playgrounds
from app.main import app
from app.security import create_token


@pytest.fixture
def context(monkeypatch):
    rows={'META':{'status':'open'},'TEAM#team-a':{},'USER#alice':{'team_id':'team-a'}}
    rows['TEAM#team-a']={'team_id':'team-a'}
    calls=[]
    monkeypatch.setattr(playgrounds,'get_item',lambda pk,sk:rows.get(sk) if pk=='EVENT#event-a' else None)
    monkeypatch.setattr(playgrounds.settings,'playground_manager_url','http://private-manager')
    monkeypatch.setattr(playgrounds,'control',lambda path,body=None:calls.append((path,body)) or {'status':'queued'})
    token=create_token({'sub':'alice','role':'participant','event_id':'event-a','team_id':'team-a'})
    return rows,calls,{'Authorization':'Bearer '+token}


def test_participant_cannot_provision_reference_template(context):
    rows,calls,headers=context
    client=TestClient(app)
    response=client.post('/api/v1/participant/playground?team_id=another-team',headers=headers,json={'lab_id':'victim','endpoint':'http://attacker'})
    assert response.status_code==409
    assert calls==[]


def test_reference_inventory_is_not_a_participant_deployment(context,monkeypatch):
    _,calls,headers=context
    monkeypatch.setattr(playgrounds,'control',lambda *args:pytest.fail('Reference inventory must not be queried'))
    response=TestClient(app).get('/api/v1/participant/playground?lab_id=victim',headers=headers)
    assert response.status_code==200
    assert response.json()['status']=='awaiting_deployment'
    assert response.json()['snapshot'] is None
    assert 'lab_id' not in response.json()


def test_only_atomic_receipt_and_matching_lab_provenance_expose_inventory(context,monkeypatch):
    rows,calls,headers=context
    receipt={'status':'applied','validator':'aws-event-driven-deploy-v1','lab_key':'a'*64,
        'evaluation_id':'id','commit_sha':'a'*40,'source_digest':'b'*64,'repo_name':'student/lab'}
    rows['DEPLOY#team-a']=receipt
    monkeypatch.setattr(playgrounds,'control',lambda *args:{'status':'parked','snapshot':{'tables':['orders']},'deployment':receipt})
    assert TestClient(app).get('/api/v1/participant/playground',headers=headers).json()['snapshot']=={'tables':['orders']}
    monkeypatch.setattr(playgrounds,'control',lambda *args:{'status':'parked','snapshot':{'tables':['wrong']},'deployment':{**receipt,'commit_sha':'c'*40}})
    assert TestClient(app).get('/api/v1/participant/playground',headers=headers).json()['snapshot'] is None


@pytest.mark.parametrize('change',['revoked','wrong-team','missing-team','finished'])
def test_revoked_or_foreign_members_cannot_read_or_prepare(context,change):
    rows,calls,headers=context
    if change=='revoked':del rows['USER#alice']
    elif change=='wrong-team':rows['USER#alice']['team_id']='victim'
    elif change=='missing-team':del rows['TEAM#team-a']
    else:rows['META']['status']='finished'
    for method in ('get','post'):
        assert getattr(TestClient(app),method)('/api/v1/participant/playground',headers=headers).status_code==403
    assert not calls


def test_pause_permits_snapshot_only(context):
    rows,calls,headers=context
    rows['META']['status']='paused'
    client=TestClient(app)
    assert client.get('/api/v1/participant/playground',headers=headers).status_code==200
    assert client.post('/api/v1/participant/playground',headers=headers).status_code==409
    assert not calls


def test_playground_and_internal_routes_reject_anonymous_requests():
    client=TestClient(app)
    assert client.get('/api/v1/participant/playground').status_code==401
    assert client.post('/api/v1/participant/playground').status_code==401
    assert client.get('/internal/playgrounds/events/test').status_code==401
