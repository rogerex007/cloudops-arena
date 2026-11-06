from copy import deepcopy
from botocore.exceptions import ClientError
import pytest
from app import mission_scheduler as scheduler

@pytest.fixture
def scheduled(monkeypatch):
    event={'PK':'EVENT#test','type':'event','status':'open','game_pack':'pack','active_mission_id':'one','mission_deadline':100}
    writes=[]
    class Table:
        def update_item(self,**kw):writes.append(kw)
    monkeypatch.setattr(scheduler,'scan_items',lambda *a:[event])
    monkeypatch.setattr(scheduler,'table_resource',lambda:Table())
    monkeypatch.setattr(scheduler,'load_pack',lambda _: {'missions':[{'id':'one','duration_minutes':5},{'id':'two','duration_minutes':15}]})
    return event,writes


def test_expired_mission_advances_with_full_next_duration(scheduled):
    event,writes=scheduled
    assert scheduler.advance_due_missions(200)==1
    values=writes[0]['ExpressionAttributeValues']
    assert values[':next']=='two' and values[':next_deadline']==1100 and values[':seconds']==900
    assert 'active_mission_id=:active' in writes[0]['ConditionExpression']
    assert 'mission_deadline=:deadline' in writes[0]['ConditionExpression']
    assert '#status=:open' in writes[0]['ConditionExpression']
    assert len(writes)==1 # No scores, completions or participant records are written.


@pytest.mark.parametrize('changes',[{'status':'paused'},{'status':'finished'},{'mission_deadline':None},{'mission_deadline':201},{'mission_sequence_complete':True},{'auto_advance_missions':False}])
def test_paused_untimed_finished_and_future_missions_do_not_advance(scheduled,changes):
    event,writes=scheduled;event.update(changes)
    assert scheduler.advance_due_missions(200)==0 and not writes


def test_last_mission_closes_without_finishing_event_or_awarding_points(scheduled):
    event,writes=scheduled;event['active_mission_id']='two'
    assert scheduler.advance_due_missions(200)==1
    expression=writes[0]['UpdateExpression']
    assert 'mission_sequence_complete=:true' in expression
    assert 'active_mission_id' not in expression and '#status' not in expression


def test_concurrent_pause_restart_or_second_scheduler_cannot_overwrite(scheduled,monkeypatch):
    class RacingTable:
        def update_item(self,**kw):raise ClientError({'Error':{'Code':'ConditionalCheckFailedException'}},'UpdateItem')
    monkeypatch.setattr(scheduler,'table_resource',lambda:RacingTable())
    assert scheduler.advance_due_missions(200)==0
