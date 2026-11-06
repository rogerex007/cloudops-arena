import pytest
from fastapi import HTTPException
from app import main,mission_scheduler
from app.mission_clock import clock,require_time


def test_create_event_accepts_registration_without_starting_clock(monkeypatch):
    written=[]
    class Table:
        def put_item(self,Item,**kw):written.append(Item)
    monkeypatch.setattr(main,'table_resource',lambda:Table())
    monkeypatch.setattr(main,'load_pack',lambda _: {'missions':[{'id':'first','duration_minutes':5}]})
    main.create_event(main.EventCreateRequest(title='Waiting workshop'),{})
    event=written[0]
    assert event['status']=='open' and event['active_mission_id']==''
    assert event['missions_started'] is False and 'mission_deadline' not in event
    assert clock(event)['waiting'] and clock(event)['closed']
    with pytest.raises(HTTPException) as error:require_time(event)
    assert error.value.status_code==409


def test_instructor_activation_starts_first_clock_and_clears_sequence_end(monkeypatch):
    event={'missions_started':False,'game_pack':'pack'};writes=[]
    class Table:
        def update_item(self,**kw):writes.append(kw)
    monkeypatch.setattr(main,'get_item',lambda *a:event)
    monkeypatch.setattr(main,'table_resource',lambda:Table())
    monkeypatch.setattr(main,'load_pack',lambda _: {'missions':[{'id':'first','duration_minutes':5},{'id':'second','duration_minutes':15}]})
    monkeypatch.setattr(main.time,'time',lambda:1000)
    with pytest.raises(HTTPException):main.activate_mission('event',main.ActivateMissionRequest(mission_id='second'),{})
    assert not writes
    main.activate_mission('event',main.ActivateMissionRequest(mission_id='first'),{})
    assert writes[0]['ExpressionAttributeValues'][':started'] is True
    assert writes[0]['ExpressionAttributeValues'][':deadline']==1300
    assert 'REMOVE mission_sequence_complete' in writes[0]['UpdateExpression']


def test_waiting_room_never_advances_even_with_stale_deadline(monkeypatch):
    monkeypatch.setattr(mission_scheduler,'scan_items',lambda *a:[{'status':'open','mission_deadline':1,'missions_started':False}])
    monkeypatch.setattr(mission_scheduler,'table_resource',lambda:pytest.fail('Waiting room must not advance'))
    assert mission_scheduler.advance_due_missions(1000)==0
