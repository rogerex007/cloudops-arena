from copy import deepcopy

import pytest
from boto3.dynamodb.types import TypeDeserializer
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app import evaluations, main
from app.security import create_token, require_participant

PK = "EVENT#event-1"
PRINCIPAL = {"sub": "user-1", "role": "participant", "event_id": "event-1", "team_id": "team-1"}
SHA = "a" * 40


class Store:
    class exceptions:
        class TransactionCanceledException(Exception):
            pass

    def __init__(self):
        self.items = {
            (PK, "META"): {"type": "event", "event_id": "event-1", "game_pack": "pack", "status": "open", "active_mission_id": "mission-02"},
            (PK, "TEAM#team-1"): {"type": "team", "team_id": "team-1", "name": "Ana", "repo_name": "ana/lab", "score": 1},
            (PK, "USER#user-1"): {"team_id": "team-1"},
        }
        self.transactions = []
        self.before_write = None

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": deepcopy(item)} if item else {}

    def transact_write_items(self, *, TransactItems):
        self.transactions.append(TransactItems)
        if self.before_write:
            self.before_write()
        deserialize = TypeDeserializer().deserialize
        puts = [{k: deserialize(v) for k, v in operation['Put']['Item'].items()}
                for operation in TransactItems if 'Put' in operation]
        # Simulate a concurrent writer winning the conditional insert.
        for operation in TransactItems:
            if 'Put' not in operation:
                continue
            operation = operation['Put']
            key = tuple(deserialize(operation['Item'][field]) for field in ('PK', 'SK'))
            current = self.items.get(key)
            if operation['ConditionExpression'] == 'attribute_not_exists(PK)':
                if current:
                    raise self.exceptions.TransactionCanceledException()
            elif not current or current['status'] != deserialize(operation['ExpressionAttributeValues'][':previous']) or current.get('attempt', 1) != int(deserialize(operation['ExpressionAttributeValues'][':attempt'])):
                raise self.exceptions.TransactionCanceledException()
        counter=self.items.get(('CONTROL#EVALUATIONS','QUEUE'),{}).get('outstanding',0)
        updates=[operation['Update'] for operation in TransactItems if 'Update' in operation]
        for update in updates:
            limit=int(deserialize(update['ExpressionAttributeValues'][':limit']))
            if counter>=limit:raise self.exceptions.TransactionCanceledException()
        for item in puts:
            self.items[item['PK'], item['SK']] = item
        if updates:self.items['CONTROL#EVALUATIONS','QUEUE']={'outstanding':counter+1}


@pytest.fixture
def context(monkeypatch):
    store = Store()
    monkeypatch.setattr(evaluations, "table_resource", lambda: store)
    monkeypatch.setattr(evaluations, "dynamodb_client", lambda: store)
    pack = {"version": "1.0", "missions": [
        {"id": "mission-02", "type": "lab", "workflow": ".github/workflows/official.yml"},
        {"id": "mission-03", "type": "lab", "workflow": ".github/workflows/other.yml"},
        {"id": "quiz", "type": "quiz"},
    ]}
    monkeypatch.setattr(evaluations, "load_pack", lambda _id: pack)
    # Exercise registration invariants through a test-only service adapter.
    # The production participant POST is intentionally retired (410).
    app=FastAPI()
    app.include_router(main.app.router)
    def service(mission_id:str,body:evaluations.EvaluationRequest,principal:dict=Depends(require_participant)):
        return evaluations.register_evaluation(mission_id,body,principal)
    app.add_api_route('/test/participant/missions/{mission_id}/evaluations',service,methods=['POST'])
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + create_token(PRINCIPAL)}
    return store, client, headers


def submit(context, sha=SHA, mission="mission-02"):
    _, client, headers = context
    return client.post(f"/test/participant/missions/{mission}/evaluations", json={"commit_sha": sha}, headers=headers)


def test_expired_mission_cannot_register_an_actions_delivery(context):
    import time
    store,_,_=context
    store.items[PK,'META']['mission_deadline']=int(time.time())-1
    assert submit(context).status_code==410
    assert not store.transactions


def test_records_commit_without_awarding_points_and_guards_transaction(context):
    store, _, _ = context
    response = submit(context)
    assert response.status_code == 200
    record = response.json()['evaluation']
    assert record['status'] == 'pending'
    assert record['commit_sha'] == SHA
    assert record['participant_id'] == 'user-1'
    assert 'PK' not in record
    assert store.items[PK, 'TEAM#team-1']['score'] == 1
    operations = store.transactions[0]
    assert len(operations) == 7
    event_check = operations[0]['ConditionCheck']
    assert event_check['ExpressionAttributeValues'][':open'] == {'S': 'open'}
    assert 'active_mission_id' in event_check['ConditionExpression']
    assert 'game_pack' in event_check['ConditionExpression']
    assert operations[1]['ConditionCheck']['ConditionExpression'] == 'repo_name = :repo'
    assert operations[2]['ConditionCheck']['ConditionExpression'] == 'team_id = :team'
    assert operations[3]['ConditionCheck']['Key']['SK'] == {'S': 'SUB#team-1#mission-02'}
    assert store.items[PK, 'EVAL#'+record['evaluation_id']]['repository_verified'] is False


def test_same_commit_is_idempotent_including_uppercase_sha(context):
    first = submit(context).json()
    second = submit(context, SHA.upper()).json()
    assert first['evaluation'] == second['evaluation']
    assert second['already_requested'] is True
    assert len(context[0].transactions) == 1


def test_new_commit_rejected_when_evaluation_pending(context):
    submit(context)
    assert submit(context, 'b'*40).status_code == 409
    assert sum(item.get('type') == 'evaluation' for item in context[0].items.values()) == 1


def test_one_pending_request_across_missions(context):
    submit(context)
    context[0].items[PK, 'META']['active_mission_id'] = 'mission-03'
    assert submit(context, mission='mission-03').status_code == 409


@pytest.mark.parametrize('status', ['paused', 'finished'])
def test_closed_event_rejects_request(context, status):
    context[0].items[PK, 'META']['status'] = status
    assert submit(context).status_code == 403
    assert not context[0].transactions


def test_inactive_mission_rejects_request(context):
    assert submit(context, mission='mission-03').status_code == 409
    assert not context[0].transactions


def test_missing_repo_rejects_request(context):
    context[0].items[PK, 'TEAM#team-1']['repo_name'] = ''
    assert submit(context).status_code == 409


def test_completed_mission_rejects_request(context):
    context[0].items[PK, 'SUB#team-1#mission-02'] = {'status': 'passed'}
    assert submit(context).status_code == 409


def test_removed_membership_rejects_request(context):
    context[0].items[PK, 'USER#user-1']['team_id'] = 'other-team'
    assert submit(context).status_code == 403


def test_quiz_cannot_be_submitted_as_lab(context):
    context[0].items[PK, 'META']['active_mission_id'] = 'quiz'
    assert submit(context, mission='quiz').status_code == 422


@pytest.mark.parametrize('sha', ['main', 'abc1234', 'z'*40, 'a'*41])
def test_requires_full_commit_sha(context, sha):
    assert submit(context, sha).status_code == 422
    assert not context[0].transactions


def test_requires_participant_session(context):
    _, client, _ = context
    path = '/test/participant/missions/mission-02/evaluations'
    assert client.post(path, json={'commit_sha': SHA}).status_code == 401
    admin = create_token({'sub': 'admin', 'role': 'admin'})
    assert client.post(path, json={'commit_sha': SHA}, headers={'Authorization': 'Bearer '+admin}).status_code == 403


def test_transaction_race_returns_existing_submission(context):
    store, _, _ = context
    def competing_request():
        store.before_write = None
        response = submit(context)
        assert response.status_code == 200
    store.before_write = competing_request
    response = submit(context)
    assert response.status_code == 200
    assert response.json()['already_requested'] is True


def test_event_close_during_submission_does_not_write(context):
    store, _, _ = context
    def reject():
        raise store.exceptions.TransactionCanceledException()
    store.before_write = reject
    assert submit(context).status_code == 409
    assert not any(item.get('type') == 'evaluation' for item in store.items.values())


def test_dashboard_only_exposes_current_team_evaluations(context, monkeypatch):
    store, client, headers = context
    mine = submit(context).json()['evaluation']
    rows = [{**value,'PK':key[0],'SK':key[1]} for key,value in store.items.items()]
    rows.append({**mine, 'type': 'evaluation', 'team_id': 'someone-else', 'evaluation_id': 'private'})
    monkeypatch.setattr(main, 'query_partition', lambda _pk: rows)
    monkeypatch.setattr(main, 'load_pack', lambda _id: {'missions': []})
    response = client.get('/api/v1/participant/dashboard', headers=headers)
    assert response.status_code == 200
    assert response.json()['evaluations'] == [{**mine,'queue_position':2,'queue_total':2}]


def test_retry_blocked_request_reacquires_slot_and_clears_old_result(context):
    store, client, headers = context
    result = submit(context).json()['evaluation']
    key = PK, 'EVAL#'+result['evaluation_id']
    store.items[key].update(status='blocked', message='Old error', result_code='github_unavailable')
    del store.items[PK, 'EVALLOCK#team-1']
    response = client.post('/test/participant/missions/mission-02/evaluations',
        json={'commit_sha': SHA, 'retry': True}, headers=headers)
    assert response.status_code == 200
    assert response.json()['evaluation']['status'] == 'pending'
    assert response.json()['evaluation']['attempt'] == 2
    assert response.json()['already_requested'] is False
    assert 'result_code' not in store.items[key]
    assert store.items[PK, 'EVALLOCK#team-1']['evaluation_id'] == result['evaluation_id']


def test_retry_cannot_displace_another_pending_request(context):
    store, client, headers = context
    result = submit(context).json()['evaluation']
    store.items[PK, 'EVAL#'+result['evaluation_id']]['status'] = 'blocked'
    del store.items[PK, 'EVALLOCK#team-1']
    assert submit(context, 'b'*40).status_code == 200
    response = client.post('/test/participant/missions/mission-02/evaluations',
        json={'commit_sha': SHA, 'retry': True}, headers=headers)
    assert response.status_code == 409


def test_retry_limit(context):
    store, client, headers = context
    result = submit(context).json()['evaluation']
    store.items[PK, 'EVAL#'+result['evaluation_id']].update(status='blocked', attempt=5)
    response = client.post('/test/participant/missions/mission-02/evaluations',
        json={'commit_sha': SHA, 'retry': True}, headers=headers)
    assert response.status_code == 429


def test_global_queue_cap_rejects_without_partial_lock_or_request(context,monkeypatch):
    monkeypatch.setattr(evaluations.settings,'evaluation_queue_limit',1)
    assert submit(context).status_code==200
    store,client,_=context
    store.items[PK,'TEAM#second']={'team_id':'second','repo_name':'ana/second'}
    store.items[PK,'USER#second']={'team_id':'second'}
    auth={'Authorization':'Bearer '+create_token({**PRINCIPAL,'sub':'second','team_id':'second'})}
    response=client.post('/test/participant/missions/mission-02/evaluations',headers=auth,json={'commit_sha':'b'*40})
    assert response.status_code==429
    assert (PK,'EVALLOCK#second') not in store.items
    assert store.items['CONTROL#EVALUATIONS','QUEUE']['outstanding']==1
    assert sum(row.get('type')=='evaluation' for row in store.items.values())==1


def test_fifo_uses_acceptance_time_and_retries_join_back():
    rows=[{'type':'evaluation','evaluation_id':'retry','status':'pending','created_at':'01','queued_at':'03'},
        {'type':'evaluation','evaluation_id':'first','status':'pending','created_at':'02','queued_at':'02'},
        {'type':'evaluation','evaluation_id':'active','status':'running'}]
    queue=evaluations.queue_summary(rows)
    assert queue['positions']=={'first':1,'retry':2}
    assert queue['running']==1 and queue['waiting']==2
