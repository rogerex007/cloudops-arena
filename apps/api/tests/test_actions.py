from copy import deepcopy
from types import SimpleNamespace
import time

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest

from app import actions, main, live_evaluations
from app.security import create_token

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

@pytest.fixture
def context(monkeypatch):
    now=int(time.time())
    claims={'iss':actions.ISSUER,'aud':actions.settings.actions_oidc_audience,'sub':'repo:ana/lab:ref:refs/heads/main',
        'iat':now,'nbf':now,'exp':now+300,'jti':'unique-identity','repository':'ana/lab',
        'repository_id':'12','repository_owner_id':'34','sha':'a'*40,'ref':'refs/heads/main',
        'event_name':'push','workflow_ref':'ana/lab/.github/workflows/terraform-lab.yml@refs/heads/main',
        'run_id':'56','run_attempt':'1'}
    proof={'type':'github-authorization','repository_id':12,'github_user_id':34,'repo_name':'ana/lab',
        'team_id':'team','participant_id':'user','default_branch':'main'}
    rows={'META':{'status':'open','active_mission_id':'mission-02','game_pack':'pack'},
        'TEAM#team':{'repo_name':'ana/lab'},'USER#user':{'team_id':'team'}}
    monkeypatch.setattr(actions.KEYS,'get_signing_key_from_jwt',lambda _token:SimpleNamespace(key=KEY.public_key()))
    monkeypatch.setattr(actions,'get_item',lambda _pk,sk:deepcopy(rows.get(sk)))
    monkeypatch.setattr(actions,'query_partition',lambda _pk:[proof])
    monkeypatch.setattr(actions,'load_pack',lambda _id:{'missions':[{'id':'mission-02','workflow':'.github/workflows/terraform-lab.yml'}]})
    monkeypatch.setattr(actions,'installation_token',lambda _proof:'internal-token')
    monkeypatch.setattr(actions,'api',lambda *args,**kwargs:{'id':12,'owner':{'id':34},'full_name':'ana/lab','default_branch':'main'})
    class Table:
        class meta:
            class client:
                class exceptions:
                    class ConditionalCheckFailedException(Exception):pass
        def __init__(self): self.used=set()
        def put_item(self,*,Item,ConditionExpression):
            assert ConditionExpression=='attribute_not_exists(PK)'
            if Item['PK'] in self.used:raise self.meta.client.exceptions.ConditionalCheckFailedException()
            self.used.add(Item['PK'])
    table=Table()
    monkeypatch.setattr(actions,'table_resource',lambda:table)
    captures=[]
    def register(mission,body,principal,provenance):
        captures.append((mission,body,principal,provenance))
        return {'evaluation':{'evaluation_id':'delivery','status':'pending','commit_sha':body.commit_sha}}
    monkeypatch.setattr(actions,'register_evaluation',register)
    return claims,rows,captures,TestClient(main.app)


def headers(claims,key=KEY):
    return {'Authorization':'Bearer '+jwt.encode(claims,key,algorithm='RS256')}


def post(context,claims=None):
    return context[3].post('/api/v1/actions/evaluations',headers=headers(claims or context[0]),
        json={'event_id':'event','mission_id':'mission-02','commit_sha':'b'*40,'points':1000})


def test_deploy_operation_can_follow_an_old_approval_without_resetting_points(context):
    claims,rows,captures,client=context
    rows['SUB#team#mission-02']={'status':'passed'}
    response=client.post('/api/v1/actions/evaluations',headers=headers(claims),
        json={'event_id':'event','mission_id':'mission-02','operation':'deploy'})
    assert response.status_code==200
    assert captures[0][3]['operation']=='deploy'
    assert captures[0][1].commit_sha==claims['sha']


def test_default_mission02_request_is_plan_only(context):
    assert post(context).status_code==200
    assert context[2][0][3]['operation']=='plan'


def test_signed_identity_supplies_commit_and_provenance_not_body(context):
    response=post(context)
    assert response.status_code==200
    mission,body,principal,provenance=context[2][0]
    assert body.commit_sha=='a'*40
    assert principal['sub']=='user'
    assert provenance['actions_url']=='https://github.com/ana/lab/actions/runs/56'
    assert provenance['source']=='github-actions'
    assert post(context).status_code==409
    assert len(context[2])==1


@pytest.mark.parametrize('patch',[
    {'iss':'https://evil.test'}, {'aud':'other'}, {'exp':1}, {'exp':int(time.time())+1000},
    {'event_name':'pull_request'},{'sha':'main'},{'repository_id':'not-a-number'},
    {'repository':'ana/../../lab'}, {'jti':None},
])
def test_rejects_invalid_signed_claims(context,patch):
    assert post(context,{**context[0],**patch}).status_code==401
    assert not context[2]


def test_rejects_invalid_signature_and_portal_token(context):
    wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    client=context[3]
    path='/api/v1/actions/evaluations'
    body={'event_id':'event','mission_id':'mission-02'}
    assert client.post(path,json=body,headers=headers(context[0],wrong)).status_code==401
    token=create_token({'role':'participant','sub':'user'})
    assert client.post(path,json=body,headers={'Authorization':'Bearer '+token}).status_code==401
    assert client.post(path,json=body).status_code==401


@pytest.mark.parametrize('patch',[
    {'repository_id':'99'},{'repository_owner_id':'99'},{'repository':'other/lab'},
    {'ref':'refs/heads/other'}, {'workflow_ref':'ana/lab/.github/workflows/fake.yml@refs/heads/main'},
    {'workflow_ref':'ana/lab/.github/workflows/terraform-lab.yml@refs/heads/MAIN'},
])
def test_rejects_foreign_repo_branch_or_workflow(context,patch):
    assert post(context,{**context[0],**patch}).status_code==403
    assert not context[2]


def test_paused_event_and_inactive_mission(context):
    context[1]['META']['status']='paused'
    assert post(context).status_code==403
    context[1]['META']['status']='open'
    context[1]['META']['active_mission_id']='mission-03'
    assert post(context).status_code==409


def test_already_completed_skips_without_awarding(context):
    context[1]['SUB#team#mission-02']={'points':14}
    response=post(context)
    assert response.json()['already_completed'] is True
    assert response.json()['points_awarded']==0
    assert not context[2]


def test_revoked_installation_and_membership(context,monkeypatch):
    monkeypatch.setattr(actions,'installation_token',lambda _:(_ for _ in ()).throw(actions.GitHubError('unavailable')))
    assert post(context).status_code==403
    context[1]['USER#user']['team_id']='other'
    assert post(context).status_code==403


def test_status_is_team_scoped_and_hides_private_fields(context):
    context[1]['EVAL#delivery']={'evaluation_id':'delivery','team_id':'team','mission_id':'mission-02',
        'repo_name':'ana/lab','status':'running','lease_token':'private','actions_ref':'refs/heads/main'}
    response=context[3].get('/api/v1/actions/evaluations/event/delivery',headers=headers(context[0]))
    assert response.status_code==200
    assert 'lease_token' not in response.json()['evaluation']
    context[1]['EVAL#delivery']['team_id']='other'
    assert context[3].get('/api/v1/actions/evaluations/event/delivery',headers=headers(context[0])).status_code==403


def test_sse_requires_membership_and_hides_lease(context,monkeypatch):
    principal={'role':'participant','sub':'user','event_id':'event','team_id':'team'}
    auth={'Authorization':'Bearer '+create_token(principal)}
    monkeypatch.setattr(live_evaluations,'get_item',lambda *args:{'team_id':'team'})
    monkeypatch.setattr(live_evaluations,'read_evaluation',lambda *args:{'evaluation_id':'delivery','team_id':'team','status':'passed','lease_token':'private','progress':[{'stage':'plan','status':'passed'}]})
    response=context[3].get('/api/v1/participant/evaluations/delivery/events',headers=auth)
    assert response.status_code==200
    assert 'event: evaluation' in response.text and 'private' not in response.text
    monkeypatch.setattr(live_evaluations,'get_item',lambda *args:{'team_id':'other'})
    assert context[3].get('/api/v1/participant/evaluations/delivery/events',headers=auth).status_code==403


def test_portal_evaluation_endpoint_is_retired(context):
    auth={'Authorization':'Bearer '+create_token({'role':'participant','sub':'user','event_id':'event','team_id':'team'})}
    response=TestClient(main.app).post('/api/v1/participant/missions/mission-02/evaluations',headers=auth,json={'commit_sha':'a'*40})
    assert response.status_code==410
    assert 'GitHub Actions' in response.json()['detail']
    assert not context[2]


def test_mission03_uses_its_own_workflow_and_identity_commit(context,monkeypatch):
    context[1]['META']['active_mission_id']='mission-03'
    monkeypatch.setattr(actions,'load_pack',lambda _: {'missions':[{'id':'mission-03','workflow':'.github/workflows/app-integration-tests.yml'}]})
    claims={**context[0],'workflow_ref':'ana/lab/.github/workflows/app-integration-tests.yml@refs/heads/main'}
    response=context[3].post('/api/v1/actions/evaluations',headers=headers(claims),json={'event_id':'event','mission_id':'mission-03'})
    assert response.status_code==200
    assert context[2][0][0]=='mission-03'
    assert context[2][0][1].commit_sha==claims['sha']
    assert context[2][0][3]['source']=='github-actions'


def test_mission04_identity_requires_its_own_workflow(context,monkeypatch):
    context[1]['META']['active_mission_id']='mission-04'
    monkeypatch.setattr(actions,'load_pack',lambda _: {'missions':[{'id':'mission-04','workflow':'.github/workflows/lab-integration-tests.yml'}]})
    claims={**context[0],'workflow_ref':'ana/lab/.github/workflows/lab-integration-tests.yml@refs/heads/main'}
    response=context[3].post('/api/v1/actions/evaluations',headers=headers(claims),json={'event_id':'event','mission_id':'mission-04'})
    assert response.status_code==200 and context[2][0][0]=='mission-04'
    wrong={**claims,'workflow_ref':'ana/lab/.github/workflows/app-integration-tests.yml@refs/heads/main','jti':'other'}
    assert context[3].post('/api/v1/actions/evaluations',headers=headers(wrong),json={'event_id':'event','mission_id':'mission-04'}).status_code==403
