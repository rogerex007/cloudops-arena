from copy import deepcopy
from pathlib import Path
import io
import zipfile
import yaml
import pytest
from fastapi import HTTPException
from app import main,hints,materials

ROOT=Path(__file__).resolve().parents[3]


def test_one_hour_pack_has_four_compatible_gradable_missions_and_safe_assets(monkeypatch):
    original=yaml.safe_load((ROOT/'game-packs/aws-event-driven/manifest.yaml').read_text())
    pack=yaml.safe_load((ROOT/'game-packs/aws-event-driven-60/manifest.yaml').read_text())
    assert [m['id'] for m in pack['missions']]==['mission-01','mission-02','mission-03','mission-04']
    assert sum(m['duration_minutes'] for m in pack['missions'])+pack['closing_minutes']==60
    assert sum(m['points'] for m in pack['missions'])==pack['scoring']['total_points']==75
    for old,new in zip(original['missions'],pack['missions']):
        for key in ('id','points','workflow','evaluation'):assert old.get(key)==new.get(key)
    monkeypatch.setattr(materials.settings,'game_packs_dir',str(ROOT/'game-packs'))
    for mission in pack['missions']:
        if mission.get('materials'):assert materials.build_archive(pack,mission)
    with zipfile.ZipFile(io.BytesIO(materials.build_archive(pack,pack['missions'][1]))) as archive:
        assert b'NotImplementedError' in archive.read('game-packs/aws-event-driven/functions/orders/handler.py')
        assert b'NotImplementedError' not in archive.read('game-packs/aws-event-driven/functions/payments/handler.py')
        assert b'ConditionExpression=' not in archive.read('game-packs/aws-event-driven/functions/payments/handler.py')


@pytest.fixture
def migration(monkeypatch):
    original=yaml.safe_load((ROOT/'game-packs/aws-event-driven/manifest.yaml').read_text())
    target=yaml.safe_load((ROOT/'game-packs/aws-event-driven-60/manifest.yaml').read_text())
    event={'status':'paused','game_pack':'aws-event-driven','active_mission_id':'mission-02'}
    rows=[];writes=[]
    class Table:
        def update_item(self,**kwargs):writes.append(kwargs)
    monkeypatch.setattr(main,'get_item',lambda *args:event)
    monkeypatch.setattr(main,'load_pack',lambda name:target if name=='aws-event-driven-60' else original)
    monkeypatch.setattr(main,'query_partition',lambda pk:rows)
    monkeypatch.setattr(main,'table_resource',lambda:Table())
    return event,rows,writes,target


def test_migration_changes_only_event_metadata_and_keeps_active_mission(migration):
    event,rows,writes,target=migration
    before=deepcopy(event)
    result=main.change_event_pack('event',main.EventPackRequest(game_pack='aws-event-driven-60'),{})
    assert result['missions']==4 and result['preserved_progress']
    assert len(writes)==1 and writes[0]['Key']['SK']=='META'
    assert 'SUB' not in writes[0]['UpdateExpression']
    assert writes[0]['ExpressionAttributeValues'][':active']=='mission-02'
    assert event==before


@pytest.mark.parametrize('scenario',['open','busy','different-points','removed-active'])
def test_incompatible_or_inflight_migration_is_rejected(migration,scenario):
    event,rows,writes,target=migration
    if scenario=='open':event['status']='open'
    elif scenario=='busy':rows.append({'type':'evaluation','status':'running'})
    elif scenario=='different-points':target['missions'][1]['points']=99
    else:event['active_mission_id']='mission-05'
    with pytest.raises(HTTPException) as error:main.change_event_pack('event',main.EventPackRequest(game_pack='aws-event-driven-60'),{})
    assert error.value.status_code==409 and not writes


def test_legacy_coin_credit_survives_retired_missions():
    pack={'missions':[{'id':'mission-01','coin_reward':10}],'legacy_coin_rewards':{'mission-05':10,'mission-01':10}}
    rows=[{'type':'submission','team_id':'team','mission_id':name,'status':'passed','source':'isolated-runner'} for name in ['mission-01','mission-05']]
    assert hints.wallet(pack,rows,'team')['earned']==20


def test_architecture_references_real_shared_idempotency_table():
    pack=yaml.safe_load((ROOT/'game-packs/aws-event-driven-60/manifest.yaml').read_text())
    architecture=pack['architecture'];nodes={node['id']:node for node in architecture['nodes']}
    assert {node['id'] for node in nodes.values() if node['kind']=='database'}=={'ordersdb','idempotency'}
    assert {(edge['from'],edge['to']) for edge in architecture['edges'] if edge['to']=='idempotency'}=={('payments','idempotency'),('inventory','idempotency')}
    assert all(edge['from'] in nodes and edge['to'] in nodes for edge in architecture['edges'])
