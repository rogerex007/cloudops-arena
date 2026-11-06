import hashlib
import hmac
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import main, materials
from app.config import settings
from app.gamepack import public_missions
from app.security import create_token

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def context(monkeypatch):
    pack = yaml.safe_load((ROOT/'game-packs/aws-event-driven/manifest.yaml').read_text())
    mission = next(m for m in pack['missions'] if m['id']=='mission-02')
    rows = {
        'META': {'game_pack':pack['id'], 'active_mission_id':'mission-02', 'status':'open'},
        'USER#user': {'team_id':'team'},
    }
    def read(pk, sk):
        assert pk == 'EVENT#event'
        return rows.get(sk)
    monkeypatch.setattr(materials, 'get_item', read)
    monkeypatch.setattr(materials, 'load_pack', lambda _id: pack)
    monkeypatch.setattr(settings, 'game_packs_dir', str(ROOT/'game-packs'))
    client = TestClient(main.app)
    headers = {'Authorization':'Bearer '+create_token({'sub':'user', 'role':'participant', 'event_id':'event', 'team_id':'team'})}
    return client, headers, rows, pack, mission


def download(context):
    client, headers, *_ = context
    return client.get('/api/v1/participant/missions/mission-02/materials', headers=headers)


def test_download_contains_complete_structure_and_versioned_metadata(context):
    response = download(context)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert 'aws-event-driven-1.0.0-mission-02-starter.zip' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'private, no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        mission = context[4]
        assert set(mission['evaluation']['required_files']) <= names
        assert {'README.md','LICENSE','.gitignore','ARENA-KIT.json'} <= names
        assert archive.read('LICENSE') == (ROOT/'LICENSE').read_bytes()
        assert all(not name.startswith('/') and '..' not in name.split('/') for name in names)
        metadata = json.loads(archive.read('ARENA-KIT.json'))
        assert metadata['game_pack']=='aws-event-driven'
        assert metadata['pack_version']=='1.0.0'
        assert metadata['mission_id']=='mission-02'
        for name, digest in metadata['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_no_solutions_validators_or_secrets_are_bundled(context):
    with zipfile.ZipFile(io.BytesIO(download(context).content)) as archive:
        for name in archive.namelist():
            assert not any(part in {'.env','.secrets','tests','validators'} for part in name.split('/'))
            assert not name.endswith(('manifest.yaml','.tfstate','.tfvars'))
        for service in ('orders','payments','inventory'):
            code = archive.read(f'game-packs/aws-event-driven/functions/{service}/handler.py').decode()
            assert 'raise NotImplementedError' in code
            assert 'boto3' not in code
            compile(code, service, 'exec')
        workflow = archive.read('.github/workflows/terraform-lab.yml').decode()
        assert 'ubuntu-latest' in workflow
        assert 'self-hosted' not in workflow
        assert 'terraform apply' not in workflow


def test_archive_is_reproducible(context):
    first, second = download(context), download(context)
    assert first.content == second.content
    assert first.headers['etag'] == second.headers['etag']


def test_requires_participant_login(context):
    client = context[0]
    assert client.get('/api/v1/participant/missions/mission-02/materials').status_code == 401
    headers = {'Authorization':'Bearer '+create_token({'sub':'admin','role':'admin'})}
    assert client.get('/api/v1/participant/missions/mission-02/materials',headers=headers).status_code == 403


def test_locked_mission_materials_are_not_accessible(context):
    context[2]['META']['active_mission_id']='mission-01'
    assert download(context).status_code == 403


def test_completed_mission_remains_downloadable(context):
    context[2]['META']['active_mission_id']='mission-03'
    context[2]['META']['status']='finished'
    context[2]['SUB#team#mission-02']={'status':'passed'}
    assert download(context).status_code == 200


def test_removed_membership_cannot_download(context):
    context[2]['USER#user']['team_id']='other'
    assert download(context).status_code == 403


def test_paused_event_allows_reading_active_materials(context):
    context[2]['META']['status']='paused'
    assert download(context).status_code == 200


def test_mission_without_kit_returns_not_found(context):
    del context[4]['materials']
    assert download(context).status_code == 404


@pytest.mark.parametrize('source,destination', [
    ('../../README.md','README.md'),
    ('/etc/passwd','README.md'),
    ('starter/README.md','../outside.md'),
    ('starter/README.md','/absolute.md'),
    ('starter/README.md','folder\\outside.md'),
    ('.env','file.txt'),
    ('starter/README.md','.env'),
    ('tests/smoke_test.py','file.py'),
    ('starter/README.md','terraform.tfstate'),
    ('starter/README.md','ARENA-KIT.json'),
])
def test_rejects_unsafe_material_configuration(context,source,destination):
    context[4]['materials']['files']=[{'source':source,'destination':destination}]
    assert download(context).status_code == 503


def test_symlink_cannot_escape_pack_root(context,monkeypatch,tmp_path):
    packroot=tmp_path/'aws-event-driven'
    packroot.mkdir()
    outside=tmp_path/'secret.txt'
    outside.write_text('not for participants')
    (packroot/'linked.md').symlink_to(outside)
    monkeypatch.setattr(settings,'game_packs_dir',str(tmp_path))
    context[4]['materials']['files']=[{'source':'linked.md','destination':'README.md'}]
    assert download(context).status_code == 503


def test_size_limit_rejects_large_asset(context,monkeypatch):
    monkeypatch.setattr(materials,'MAX_FILE_BYTES',16)
    assert download(context).status_code == 503


def test_no_duplicate_destination(context):
    entry = context[4]['materials']['files'][0]
    context[4]['materials']['files']=[entry,deepcopy(entry)]
    assert download(context).status_code == 503


def test_dashboard_only_exposes_public_material_metadata(context):
    pack=context[3]
    mission=next(m for m in public_missions(pack) if m['id']=='mission-02')
    assert set(mission['materials']) == {'title','filename','instructions'}
    assert 'source' not in json.dumps(mission['materials'])


def test_preview_can_disable_legacy_workflow_scoring(monkeypatch):
    monkeypatch.setattr(settings,'github_legacy_scoring_enabled',False)
    monkeypatch.setattr(settings,'github_webhook_secret','local-test-secret')
    award = []
    monkeypatch.setattr(main,'award_mission',lambda *args: award.append(args))
    payload=json.dumps({'action':'completed','workflow_run':{'conclusion':'success','head_branch':'main'}}).encode()
    headers={'X-GitHub-Event':'workflow_run','X-Hub-Signature-256':'sha256='+hmac.new(b'local-test-secret',payload,hashlib.sha256).hexdigest()}
    response=TestClient(main.app).post('/api/v1/webhooks/github',content=payload,headers=headers)
    assert response.status_code == 200
    assert response.json()['ignored'] is True
    assert not award
    headers['X-Hub-Signature-256']='invalid'
    assert TestClient(main.app).post('/api/v1/webhooks/github',content=payload,headers=headers).status_code == 401


def test_mission03_archive_only_adds_workflow_and_contract(context):
    client,headers,rows,*_=context
    rows['META']['active_mission_id']='mission-03'
    response=client.get('/api/v1/participant/missions/mission-03/materials',headers=headers)
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'MISSION-03.md','ARENA-KIT.json','.github/workflows/app-integration-tests.yml'}
        workflow=archive.read('.github/workflows/app-integration-tests.yml').decode()
        assert "'mission_id': 'mission-03'" in workflow
        assert 'id-token: write' in workflow and 'CloudOps-Arena-Actions/1.0' in workflow
        assert 'self-hosted' not in workflow
        assert json.loads(archive.read('ARENA-KIT.json'))['mission_id']=='mission-03'


def test_mission04_archive_only_adds_workflow_and_contract(context):
    client,headers,rows,*_=context
    rows['META']['active_mission_id']='mission-04'
    response=client.get('/api/v1/participant/missions/mission-04/materials',headers=headers)
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'MISSION-04.md','ARENA-KIT.json','.github/workflows/lab-integration-tests.yml'}
        workflow=archive.read('.github/workflows/lab-integration-tests.yml').decode()
        assert "'mission_id': 'mission-04'" in workflow
        assert 'id-token: write' in workflow and 'CloudOps-Arena-Actions/1.0' in workflow
        assert 'self-hosted' not in workflow and 'terraform apply' not in workflow
        assert 'OPERATIONS_URL' in archive.read('MISSION-04.md').decode()
