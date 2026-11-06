from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app import evaluation_worker as worker


def test_deployment_serializes_dynamodb_decimal_attempt(item,monkeypatch,tmp_path):
    import base64,hashlib,io,json
    from decimal import Decimal
    secret=tmp_path/'token';secret.write_text('test-only-token')
    monkeypatch.setattr(worker.settings,'evaluation_runner_token_file',str(secret))
    monkeypatch.setattr(worker.settings,'playground_manager_url','http://manager')
    monkeypatch.setattr(worker,'record_progress',Mock())
    monkeypatch.setattr(worker,'table_resource',Mock())
    item.update(event_id='event',operation='deploy',attempt=Decimal('2'),lease_token='lease')
    files={'fixture.py':base64.b64encode(b'fixture').decode()}
    source={'files':files,'repository_verified':True,'validator':'aws-event-driven-deploy-v1',
        'repository_id':12,'installation_id':13,'authorized_participant_id':'user'}
    hashes={'fixture.py':hashlib.sha256(b'fixture').hexdigest()}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    captured=[]
    def open_request(request,timeout):
        payload=json.loads(request.data)
        captured.append(payload)
        assert type(payload['attempt']) is int and payload['attempt']==2
        return io.BytesIO(json.dumps({'status':'passed','validator':source['validator'],
            'source_digest':digest,'run_id':'a'*32}).encode())
    monkeypatch.setattr(worker,'build_opener',lambda *_args:Mock(open=open_request))
    original=worker.internal_json
    monkeypatch.setattr(worker,'internal_json',lambda url,*args:source if url.endswith('/source') else original(url,*args))
    assert worker.execute_plan(item)['status']=='passed'
    assert len(captured)==1


@pytest.fixture
def item(monkeypatch):
    monkeypatch.setattr(worker, 'load_pack', lambda _id: {'version':'1.0', 'missions':[
        {'id':'mission-02', 'evaluation': {'required_files':['terraform/main.tf', 'functions/orders.py']}}]})
    return {'PK':'EVENT#event', 'SK':'EVAL#id', 'evaluation_id':'id', 'team_id':'team',
            'participant_id':'user', 'repo_name':'student/lab', 'commit_sha':'a'*40,
            'game_pack':'pack', 'pack_version':'1.0', 'mission_id':'mission-02',
            'status':'pending', 'created_at':'2026-11-04T00:00:00Z'}


def source(entries=None, **overrides):
    def get(path):
        if '/commits/' in path:
            return {'sha':'a'*40, 'tree':{'sha':'b'*40}}
        return {'sha':'b'*40, 'truncated':False, 'tree': entries or [], **overrides}
    return get


def test_reports_missing_files_without_execution(item):
    result = worker.inspect_source(item, source())
    assert result['status'] == 'failed'
    assert result['missing_files'] == ['functions/orders.py', 'terraform/main.tf']


def test_symlinks_do_not_satisfy_required_files(item):
    entries = [{'path':path, 'type':'blob', 'mode':'120000'} for path in ['terraform/main.tf', 'functions/orders.py']]
    assert worker.inspect_source(item, source(entries))['result_code'] == 'missing_files'


def test_complete_tree_never_passes_lab_or_grants_points(item):
    entries = [{'path':path, 'type':'blob', 'mode':'100644'} for path in ['terraform/main.tf', 'functions/orders.py']]
    result = worker.inspect_source(item, source(entries))
    assert result['status'] == 'blocked'
    assert result['result_code'] == 'isolated_runner_required'
    assert 'points' not in result


def test_rejects_truncated_tree(item):
    assert worker.inspect_source(item, source(truncated=True))['result_code'] == 'incomplete_tree'


def test_rejects_mismatched_commit(item):
    assert worker.inspect_source(item, lambda _path: {'sha':'wrong'})['result_code'] == 'commit_mismatch'


def test_private_or_unavailable_source_is_blocked(item):
    def fail(_path):
        raise worker.GitHubReadError('source_unavailable', 'Not available')
    assert worker.inspect_source(item, fail)['status'] == 'blocked'


def test_invalid_repository_never_causes_network_request(item):
    item['repo_name'] = 'localhost/../../secrets'
    read = Mock()
    assert worker.inspect_source(item, read)['result_code'] == 'invalid_source'
    read.assert_not_called()


def test_changed_pack_cannot_use_new_validator(item):
    item['pack_version'] = '0.9'
    read = Mock()
    assert worker.inspect_source(item, read)['result_code'] == 'pack_changed'
    read.assert_not_called()


def test_only_one_worker_can_claim_request(item, monkeypatch):
    table = Mock()
    table.update_item.side_effect = ClientError({'Error':{'Code':'ConditionalCheckFailedException'}},'UpdateItem')
    monkeypatch.setattr(worker, 'table_resource', lambda: table)
    assert worker.claim(item) is None
    assert table.update_item.call_args.kwargs['ConditionExpression'] == '#state = :pending'


def test_claim_establishes_bounded_lease(item, monkeypatch):
    table = Mock()
    monkeypatch.setattr(worker, 'table_resource', lambda: table)
    result = worker.claim(item, now=100)
    assert result['lease_expires_at'] == 220
    assert result['status'] == 'preparing'
    assert result['lease_token']


def test_finish_atomically_records_result_and_releases_matching_slot(item, monkeypatch):
    item['lease_token'] = 'lease'
    client = Mock()
    monkeypatch.setattr(worker, 'dynamodb_client', lambda: client)
    assert worker.finish(item, {'status':'failed', 'result_code':'missing_files', 'message':'Missing files'})
    operations = client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(operations) == 2
    update, delete = operations[0]['Update'], operations[1]['Delete']
    assert 'lease_token = :token' in update['ConditionExpression']
    assert update['ExpressionAttributeValues'][':token'] == {'S':'lease'}
    assert delete['ConditionExpression'] == 'evaluation_id = :evaluation'
    assert delete['ExpressionAttributeValues'][':evaluation'] == {'S':'id'}
    # No submission or team score write exists in this transaction.
    assert update['Key']['SK'] == {'S':'EVAL#id'}
    assert delete['Key']['SK'] == {'S':'EVALLOCK#team'}


def test_preflight_refuses_success_result(item):
    with pytest.raises(ValueError):
        worker.finish(item, {'status':'passed'})


def test_plan_mode_never_awards_points_even_when_caller_requests_scoring(item,monkeypatch):
    item.update(operation='plan',status='running',repository_verified=True,lease_token='lease')
    client=Mock();monkeypatch.setattr(worker,'dynamodb_client',lambda:client)
    result={'status':'passed','validator':'aws-event-driven-plan-v1','result_code':'terraform_plan_passed','run_id':'a'*32}
    assert worker.finish(item,result)
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(operations)==2


def test_deploy_cannot_reuse_plan_approval(item):
    item.update(operation='deploy',status='running',repository_verified=True,lease_token='lease')
    with pytest.raises(ValueError,match='apply evidence'):
        worker.finish(item,{'status':'passed','validator':'aws-event-driven-plan-v1','result_code':'terraform_plan_passed'})


def test_stale_worker_cannot_overwrite_retry_or_release_new_slot(item, monkeypatch):
    class Client:
        class exceptions:
            class TransactionCanceledException(Exception): pass
        def transact_write_items(self, **_kwargs):
            raise self.exceptions.TransactionCanceledException()
    item['lease_token'] = 'old-lease'
    monkeypatch.setattr(worker, 'dynamodb_client', lambda: Client())
    assert worker.finish(item, {'status':'blocked', 'result_code':'worker_interrupted'}) is False


def test_expiry_recovery_is_conditional(item, monkeypatch):
    item['lease_token'] = 'lease'
    client = Mock()
    monkeypatch.setattr(worker, 'dynamodb_client', lambda: client)
    worker.finish(item, {'status':'blocked', 'result_code':'worker_interrupted'}, expired=True)
    update = client.transact_write_items.call_args.kwargs['TransactItems'][0]['Update']
    assert 'lease_expires_at <= :now' in update['ConditionExpression']


def test_passed_result_requires_authorized_running_vm_and_atomic_points(item,monkeypatch):
    item.update(status='running',repository_verified=True,repository_id=22,installation_id=33,
                authorized_participant_id='user',lease_token='lease')
    monkeypatch.setattr(worker,'load_pack',lambda _: {'version':'1.0','missions':[{'id':'mission-02','workflow_points':14}]})
    client=Mock()
    monkeypatch.setattr(worker,'dynamodb_client',lambda:client)
    result={'status':'passed','result_code':'terraform_plan_passed','validator':'aws-event-driven-plan-v1','run_id':'a'*32,'message':'Passed'}
    assert worker.finish(item,result)
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert len(operations)==6
    submission=operations[2]['Put']
    assert submission['ConditionExpression']=='attribute_not_exists(PK)'
    assert submission['Item']['points']=={'N':'14'}
    assert submission['Item']['source']=={'S':'isolated-runner'}
    assert operations[3]['Update']['ExpressionAttributeValues'][':points']=={'N':'14'}
    assert operations[5]['ConditionCheck']['Key']['SK']=={'S':'GHAUTH#team'}


@pytest.mark.parametrize('verified,status,validator',[(False,'running','aws-event-driven-plan-v1'),(True,'preparing','aws-event-driven-plan-v1'),(True,'running','participant-validator')])
def test_untrusted_success_cannot_award(item,verified,status,validator):
    item.update(repository_verified=verified,status=status)
    with pytest.raises(ValueError):
        worker.finish(item,{'status':'passed','result_code':'terraform_plan_passed','validator':validator})


def test_membership_removed_before_processing_blocks_source_access(item, monkeypatch):
    claimed = {**item, 'lease_token':'lease'}
    monkeypatch.setattr(worker, 'claim', lambda _item: claimed)
    monkeypatch.setattr(worker, 'get_item', lambda *_args: None)
    inspector = Mock()
    finish = Mock()
    monkeypatch.setattr(worker, 'inspect_source', inspector)
    monkeypatch.setattr(worker, 'finish', finish)
    worker.process_one(item)
    inspector.assert_not_called()
    assert finish.call_args.args[1]['result_code'] == 'binding_changed'


def test_progress_is_curated_and_requires_live_lease(item,monkeypatch):
    table=Mock()
    monkeypatch.setattr(worker,'table_resource',lambda:table)
    item['lease_token']='current'
    worker.record_progress(item,{'stage':'plan','status':'running','message':'untrusted stdout','secret':'do not forward'})
    event=item['progress'][-1]
    assert event['message']=='Generación del plan' and 'secret' not in event
    condition=table.update_item.call_args.kwargs['ConditionExpression']
    assert 'lease_token = :token' in condition and 'lease_expires_at > :expires' in condition
    with pytest.raises(ValueError):worker.record_progress(item,{'stage':'arbitrary stdout','status':'passed'})


@pytest.mark.parametrize('frames,valid',[
    ([{'type':'progress','event':{'stage':'plan','status':'passed'}},{'type':'result','result':{'status':'passed'}}],True),
    ([{'type':'result','result':{}},{'type':'result','result':{}}],False),
    ([{'type':'progress','event':{'stage':'plan','status':'running'}}],False),
    ([{'type':'result','result':{}},{'type':'progress','event':{'stage':'plan','status':'passed'}}],False),
    ([{'type':'error','error':'unavailable'}],False),
])
def test_stream_requires_exactly_one_final_result(item,monkeypatch,frames,valid):
    import io,json
    from contextlib import nullcontext
    response=io.BytesIO(b''.join(json.dumps(frame).encode()+b'\n' for frame in frames))
    response.headers={'Content-Type':'application/x-ndjson'}
    opener=Mock()
    opener.open.return_value=nullcontext(response)
    monkeypatch.setattr(worker,'build_opener',lambda *_:opener)
    progress=[]
    monkeypatch.setattr(worker,'record_progress',lambda _item,event:progress.append(event))
    if valid:
        assert worker.runner_stream('http://runner/evaluate','secret',{},item)=={'status':'passed'}
        assert progress==[{'stage':'plan','status':'passed'}]
    else:
        with pytest.raises(ValueError):worker.runner_stream('http://runner/evaluate','secret',{},item)


def test_runtime_grade_awards_twenty_and_cannot_grade_wrong_mission(item,monkeypatch):
    item.update(mission_id='mission-03',status='running',repository_verified=True,repository_id=22,
        installation_id=33,authorized_participant_id='user',lease_token='lease')
    monkeypatch.setattr(worker,'load_pack',lambda _: {'version':'1.0','missions':[{'id':'mission-03','points':20}]})
    client=Mock();monkeypatch.setattr(worker,'dynamodb_client',lambda:client)
    result={'status':'passed','validator':'aws-event-driven-runtime-v1','result_code':'runtime_flow_passed','message':'Passed','run_id':'a'*32}
    assert worker.finish(item,result)
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert operations[2]['Put']['Item']['points']=={'N':'20'}
    item['mission_id']='mission-02'
    with pytest.raises(ValueError):worker.finish(item,result)
    item['mission_id']='mission-03'
    with pytest.raises(ValueError):worker.finish(item,{**result,'validator':'aws-event-driven-plan-v1','result_code':'terraform_plan_passed'})


def test_resilience_grade_is_thirty_points_and_mission_bound(item,monkeypatch):
    item.update(mission_id='mission-04',status='running',repository_verified=True,repository_id=22,
        installation_id=33,authorized_participant_id='user',lease_token='lease')
    monkeypatch.setattr(worker,'load_pack',lambda _: {'version':'1.0','missions':[{'id':'mission-04','points':30}]})
    client=Mock();monkeypatch.setattr(worker,'dynamodb_client',lambda:client)
    result={'status':'passed','validator':'aws-event-driven-resilience-v1','result_code':'resilience_flow_passed','message':'Passed','run_id':'a'*32}
    assert worker.finish(item,result)
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert operations[2]['Put']['Item']['points']=={'N':'30'}
    item['mission_id']='mission-03'
    with pytest.raises(ValueError):worker.finish(item,result)
    item['mission_id']='mission-04'
    with pytest.raises(ValueError):worker.finish(item,{**result,'validator':'aws-event-driven-runtime-v1','result_code':'runtime_flow_passed'})


def test_busy_runner_is_retried_before_blocking(item,monkeypatch):
    import io,json
    from contextlib import nullcontext
    from urllib.error import HTTPError
    response=io.BytesIO(json.dumps({'type':'result','result':{'status':'passed'}}).encode()+b'\n')
    response.headers={'Content-Type':'application/x-ndjson'}
    opener=Mock()
    opener.open.side_effect=[HTTPError('http://runner',409,'Busy',{},None),nullcontext(response)]
    monkeypatch.setattr(worker,'build_opener',lambda *_:opener)
    sleep=Mock();monkeypatch.setattr(worker.time,'sleep',sleep)
    assert worker.runner_stream('http://runner/evaluate','secret',{},item)=={'status':'passed'}
    assert opener.open.call_count==2
    sleep.assert_called_once_with(3)


def test_busy_runner_wait_has_deadline(item,monkeypatch):
    from urllib.error import HTTPError
    opener=Mock();opener.open.side_effect=HTTPError('http://runner',409,'Busy',{},None)
    monkeypatch.setattr(worker,'build_opener',lambda *_:opener)
    monkeypatch.setattr(worker.time,'monotonic',Mock(side_effect=[0,61]))
    assert worker.runner_stream('http://runner/evaluate','secret',{},item)['error_result']['status']=='blocked'
    assert opener.open.call_count==1


def test_finalization_releases_queue_capacity_atomically(item,monkeypatch):
    item.update(lease_token='lease',queue_accounted=True)
    client=Mock();monkeypatch.setattr(worker,'dynamodb_client',lambda:client)
    assert worker.finish(item,{'status':'failed','result_code':'validation_failed'})
    operations=client.transact_write_items.call_args.kwargs['TransactItems']
    assert operations[-1]['Update']['Key']['PK']=={'S':'CONTROL#EVALUATIONS'}
    assert operations[-1]['Update']['ConditionExpression']=='outstanding >= :one'
    assert 'lease_expires_at > :now' in operations[0]['Update']['ConditionExpression']


def test_unavailable_runner_returns_to_queue_without_releasing_team_slot(item,monkeypatch):
    item['lease_token']='lease'
    monkeypatch.setattr(worker,'claim',lambda _:item)
    monkeypatch.setattr(worker,'get_item',lambda pk,sk:{'repo_name':item['repo_name'],'team_id':item['team_id']})
    monkeypatch.setattr(worker.settings,'evaluation_runner_url','http://runner')
    monkeypatch.setattr(worker,'execute_plan',lambda _: {'status':'blocked','retryable':True,'result_code':'execution_unavailable'})
    table=Mock();monkeypatch.setattr(worker,'table_resource',lambda:table)
    finish=Mock();monkeypatch.setattr(worker,'finish',finish)
    worker.process_one(item)
    finish.assert_not_called()
    update=table.update_item.call_args.kwargs
    assert update['ExpressionAttributeValues'][':pending']=='pending'
    assert 'REMOVE lease_token, lease_expires_at' in update['UpdateExpression']


def test_scheduler_does_not_claim_when_runner_has_no_credits(item,monkeypatch):
    monkeypatch.setattr(worker,'scan_items',lambda *_:[item])
    monkeypatch.setattr(worker,'runner_available',lambda:0)
    process=Mock();monkeypatch.setattr(worker,'process_one',process)
    worker.tick();process.assert_not_called()


def test_accounted_queue_requests_have_bounded_wait(item,monkeypatch):
    monkeypatch.setattr(worker.settings,'evaluation_queue_wait_seconds',60)
    item.update(queue_accounted=True,queued_at='1970-01-01T00:00:00+00:00')
    assert worker.queue_expired(item,61)
    assert not worker.queue_expired(item,59)
    item['queue_accounted']=False
    assert not worker.queue_expired(item,61)


def test_scheduler_dispatches_fifo_and_never_exceeds_two_futures(item,monkeypatch):
    monkeypatch.setattr(worker.settings,'evaluation_concurrency',2)
    rows=[{**item,'evaluation_id':name,'SK':'EVAL#'+name,'queued_at':stamp} for name,stamp in [('third','03'),('first','01'),('second','02')]]
    monkeypatch.setattr(worker,'scan_items',lambda *_:rows)
    monkeypatch.setattr(worker,'runner_available',lambda:2)
    future=Mock();future.done.return_value=False
    executor=Mock();executor.submit.return_value=future
    futures=[];worker.tick(executor,futures)
    assert [call.args[1]['evaluation_id'] for call in executor.submit.call_args_list]==['first','second']
    assert len(futures)==2
    worker.tick(executor,futures)
    assert executor.submit.call_count==2


def test_expired_execution_returns_to_queue_without_terminal_grade(item,monkeypatch):
    item.update(status='running',lease_token='old',lease_expires_at=0)
    monkeypatch.setattr(worker,'scan_items',lambda *_:[item])
    monkeypatch.setattr(worker,'runner_available',lambda:0)
    requeue=Mock();finish=Mock()
    monkeypatch.setattr(worker,'requeue',requeue);monkeypatch.setattr(worker,'finish',finish)
    worker.tick()
    requeue.assert_called_once_with(item);finish.assert_not_called()


def test_queue_timeout_finalizes_even_when_runner_unavailable(item,monkeypatch):
    item.update(queue_accounted=True,queued_at='1970-01-01T00:00:00+00:00')
    monkeypatch.setattr(worker,'scan_items',lambda *_:[item])
    monkeypatch.setattr(worker,'runner_available',lambda:0)
    monkeypatch.setattr(worker,'claim',lambda _: {**item,'lease_token':'test'})
    finish=Mock();monkeypatch.setattr(worker,'finish',finish)
    worker.tick()
    assert finish.call_args.args[1]['result_code']=='queue_timeout'
