"""Durability/admission contracts independent of a VM emulator."""
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'apps/playground'))
sys.path.insert(0,str(ROOT/'apps/runner'))
import manager
from capacity import Capacity
from shared_slots import take,available


@pytest.fixture
def storage(tmp_path,monkeypatch):
    monkeypatch.setattr(manager,'WORK',tmp_path)
    manager.initialize()
    return tmp_path


def test_fifo_idempotence_and_restart_keep_queue_and_snapshots(storage):
    first='a'*64;second='b'*64
    manager.enqueue(first,'event')
    manager.enqueue(second,'event')
    assert manager.enqueue(first,'event')['queue_position']==1
    assert manager.get(second)['queue_position']==2
    with manager.db() as db:
        db.execute("UPDATE labs SET state='preparing' WHERE id=?",(first,))
    manager.initialize()
    assert manager.get(first)['status']=='failed'
    manager.enqueue(first,'event')
    assert manager.get(second)['queue_position']==1


def test_fifty_lab_limit_is_atomic(storage):
    def add(index):
        try:manager.enqueue(f'{index:064x}','event');return True
        except OverflowError:return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(add,range(60)))
    assert sum(results)==50


def test_expiration_cleans_only_stopped_lab_and_its_own_files(storage):
    first='a'*64;active='b'*64
    manager.enqueue(first,'event');manager.enqueue(active,'event')
    for name in (first,active):
        (storage/name).mkdir();(storage/name/'state').write_text('private')
    with manager.db() as db:db.execute("UPDATE labs SET state='preparing' WHERE id=?",(active,))
    manager.expire_event('event');manager.expire()
    assert not (storage/first).exists()
    assert (storage/active/'state').exists()
    assert manager.get(first)['snapshot'] is None


def test_no_sdk_urls_or_rows_are_public():
    snapshot=manager.sanitize({'tables':['orders'],'functions':[],'buses':[],
        'queues':['http://private-vm:4566/account/payments'],'orders':[{'secret':'row'}],
        'processed':[],'credentials':'secret','logs':'private'})
    assert snapshot['queues']==['payments']
    assert snapshot['order_count']==1
    assert not {'orders','credentials','logs'} & snapshot.keys()


def test_deployment_rejects_missing_or_tampered_commit_files():
    payload={'event_id':'event','team_id':'team','evaluation_id':'evaluation','commit_sha':'a'*40,'files':{}}
    with pytest.raises(ValueError,match='Unexpected files'):manager.validate_deployment(payload)
    import base64
    payload['files']={name:base64.b64encode(b'test').decode() for name in manager.FILES}
    payload['source_digest']='wrong'
    with pytest.raises(ValueError,match='Digest mismatch'):manager.validate_deployment(payload)


def test_owner_capacity_counts_participants_not_retry_generations(storage):
    with manager.db() as db:
        for index in range(50):
            body={'event_id':'event','team_id':str(index)}
            manager.reserve_owner(db,body,f'{index:064x}')
        with pytest.raises(BlockingIOError):manager.reserve_owner(db,{'event_id':'event','team_id':'51'},'c'*64)
        for retry in range(5):manager.reserve_owner(db,{'event_id':'event','team_id':'0'},f'{retry+100:064x}')
        assert db.execute('SELECT count(*) FROM owners').fetchone()[0]==50


def test_replacement_keeps_old_disk_until_canonical_receipt_commits(storage,monkeypatch):
    import json
    old='a'*64;new='b'*64
    body={'event_id':'event','team_id':'team'}
    proof={'lab_key':new,'evaluation_id':'eval','source_digest':'digest','commit_sha':'commit'}
    with manager.db() as db:
        owner=manager.reserve_owner(db,body,new,old)
        for lab,provenance in [(old,{}),(new,proof)]:
            (storage/lab).mkdir();(storage/lab/'disk').write_text('state')
            db.execute("INSERT INTO labs(id,event,state,expires,owner,provenance) VALUES(?,?,'parked',9999999999,?,?)",(lab,'event',owner,json.dumps(provenance)))
    monkeypatch.setattr(manager,'owner_status',lambda *args:{'status':'open','receipt':{'lab_key':old}})
    assert not manager.activate_committed('event','team',new)
    assert (storage/old/'disk').exists()
    monkeypatch.setattr(manager,'owner_status',lambda *args:{'status':'open','receipt':proof})
    manager.reconcile_candidates()  # Worker died after committing receipt, before its ack.
    assert not (storage/old).exists() and (storage/new/'disk').exists()
    with manager.db() as db:
        owner=db.execute('SELECT active_lab,candidate FROM owners').fetchone()
        assert owner['active_lab']==new and owner['candidate'] is None


def test_manager_shutdown_waits_for_active_deploy_handler():
    import threading,urllib.request
    from http.server import BaseHTTPRequestHandler
    entered=threading.Event();release=threading.Event();closed=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            entered.set();release.wait(5);self.send_response(204);self.end_headers()
    server=manager.Server(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    def request():
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}',timeout=6):pass
    client=threading.Thread(target=request);client.start()
    assert entered.wait(2)
    server.shutdown()
    def close():server.server_close();closed.set()
    closer=threading.Thread(target=close);closer.start()
    try:assert not closed.wait(.1)
    finally:release.set();client.join(3);closer.join(3);thread.join(3)
    assert closed.is_set()


def test_replacement_reserves_time_to_preserve_previous_lab(storage):
    import time
    old='a'*64;new='b'*64;body={'event_id':'event','team_id':'team'}
    with manager.db() as db:
        db.execute("INSERT INTO labs(id,event,state,expires) VALUES(?,?,'parked',?)",(old,'event',time.time()+1))
        manager.reserve_owner(db,body,new,old)
        assert db.execute('SELECT expires FROM labs WHERE id=?',(old,)).fetchone()[0]>time.time()+590


def test_failure_stops_vm_before_making_disk_eligible_for_cleanup(storage,monkeypatch):
    lab='a'*64
    manager.enqueue(lab,'event')
    with manager.db() as db:db.execute("UPDATE labs SET state='preparing' WHERE id=?",(lab,))
    state={'alive':True,'released':False}
    class FakeVM:
        def __init__(self,_name):pass
        def boot(self):raise RuntimeError('Synthetic boot failure')
        def force_cleanup(self):state['alive']=False
    class Reservation:
        def close(self):state['released']=True
    def expire():
        assert not state['alive']
        assert state['released']
    monkeypatch.setattr(manager,'VM',FakeVM)
    monkeypatch.setattr(manager,'expire',expire)
    manager.execute(lab,Reservation())
    assert manager.get(lab)['status']=='failed'


def test_evaluators_and_playgrounds_share_two_kernel_locks(storage,monkeypatch):
    monkeypatch.setenv('VM_SLOTS_DIR',str(storage/'slots'))
    pool=Capacity(2,memory=lambda:40*1024**3,cgroup=lambda:None,disk=lambda:100*1024**3)
    assert pool.acquire()
    playground=take(storage/'slots')
    assert playground is not None
    assert not pool.acquire()
    assert available(storage/'slots')==0
    playground.close()
    assert pool.acquire()
    pool.release();pool.release()
    assert available(storage/'slots')==2
