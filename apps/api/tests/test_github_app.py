import base64
import hashlib
import json
import logging
import time
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import github_app as github, main
from app.config import settings
from app.security import create_token


class Table:
    class ConditionalCheckFailedException(Exception): pass
    def __init__(self):
        self.items={}
        self.meta=SimpleNamespace(client=SimpleNamespace(exceptions=SimpleNamespace(ConditionalCheckFailedException=self.ConditionalCheckFailedException)))
    def put_item(self,Item,**_kwargs): self.items[Item['PK'],Item['SK']]=Item.copy()
    def get_item(self,Key,**_kwargs):
        item=self.items.get((Key['PK'],Key['SK']))
        return {'Item':item.copy()} if item else {}
    def delete_item(self,Key,**kwargs):
        key=Key['PK'],Key['SK']
        if key not in self.items or self.items[key]['expires_at']<=kwargs['ExpressionAttributeValues'][':now']:
            raise self.ConditionalCheckFailedException()
        del self.items[key]


@pytest.fixture
def context(monkeypatch):
    table=Table()
    rows={'META':{'status':'open'},'TEAM#team':{'repo_name':'student/lab'},'USER#user':{'team_id':'team'}}
    monkeypatch.setattr(github,'table_resource',lambda:table)
    monkeypatch.setattr(github,'get_item',lambda pk,sk:rows.get(sk))
    config={'app_id':123,'client_id':'client','client_secret':'private-test-secret','slug':'test-arena'}
    monkeypatch.setattr(github,'credentials',lambda:(config,'test-pem'))
    monkeypatch.setattr(github,'app_token',lambda *_args:'app-token')
    client=TestClient(main.app)
    headers={'Authorization':'Bearer '+create_token({'sub':'user','role':'participant','event_id':'event','team_id':'team'})}
    return table,rows,client,headers


def start(context):
    table,rows,client,headers=context
    response=client.post('/api/v1/participant/github/authorize',headers=headers)
    assert response.status_code==200
    return parse_qs(urlsplit(response.json()['url']).query)


def test_authorization_state_is_hashed_expiring_and_pkce_bound(context):
    query=start(context)
    state=query['state'][0]
    table=context[0]
    row=next(iter(table.items.values()))
    assert row['PK']=='GHSTATE#'+hashlib.sha256(state.encode()).hexdigest()
    assert row['repo_name']=='student/lab'
    assert int(time.time())<row['expires_at']<=int(time.time())+600
    expected=base64.urlsafe_b64encode(hashlib.sha256(row['verifier'].encode()).digest()).rstrip(b'=').decode()
    assert query['code_challenge']==[expected]
    assert query['code_challenge_method']==['S256']


def test_authorize_requires_current_membership_and_open_event(context):
    context[1]['META']['status']='paused'
    assert context[2].post('/api/v1/participant/github/authorize',headers=context[3]).status_code==403


def test_callback_is_single_use_and_does_not_store_user_tokens(context,monkeypatch):
    query=start(context)
    calls=[]
    def api(path,**kwargs):
        calls.append((path,kwargs))
        if path=='/login/oauth/access_token': return {'access_token':'temporary-user-token'}
        if path=='/user': return {'id':11,'login':'student'}
        if path=='/repos/student/lab': return {'id':22,'full_name':'student/lab','owner':{'id':11}}
        if path.endswith('/installation'): return {'id':33,'account':{'id':11}}
        return {}
    monkeypatch.setattr(github,'api',api)
    database=Mock()
    monkeypatch.setattr(github,'dynamodb_client',lambda:database)
    path='/api/v1/github/callback?'+f"state={query['state'][0]}&code=temporary-code"
    response=context[2].get(path,follow_redirects=False)
    assert response.status_code==303
    assert response.headers['location'].endswith('/?github=connected')
    serialized=json.dumps(database.transact_write_items.call_args.kwargs)
    assert 'temporary-user-token' not in serialized
    assert 'temporary-code' not in serialized
    assert 'private-test-secret' not in serialized
    assert len(database.transact_write_items.call_args.kwargs['TransactItems'])==4
    assert calls[-1][1]['method']=='DELETE'
    count=len(calls)
    assert context[2].get(path,follow_redirects=False).status_code==400
    assert len(calls)==count


def test_wrong_github_owner_cannot_authorize_repository(context,monkeypatch):
    query=start(context)
    def api(path,**_kwargs):
        if path=='/login/oauth/access_token': return {'access_token':'user-token'}
        if path=='/user': return {'id':99,'login':'other'}
        if path=='/repos/student/lab': return {'id':22,'full_name':'student/lab','owner':{'id':11}}
        return {}
    monkeypatch.setattr(github,'api',api)
    database=Mock()
    monkeypatch.setattr(github,'dynamodb_client',lambda:database)
    response=context[2].get('/api/v1/github/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert response.headers['location'].endswith('/?github=error')
    database.transact_write_items.assert_not_called()


def test_expired_oauth_state_is_rejected_before_github(context,monkeypatch):
    query=start(context)
    next(iter(context[0].items.values()))['expires_at']=0
    api=Mock(); monkeypatch.setattr(github,'api',api)
    response=context[2].get('/api/v1/github/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False)
    assert response.status_code==400
    api.assert_not_called()


def test_installation_tokens_are_restricted_to_one_repository(context,monkeypatch):
    calls=[]
    def api(path,**kwargs):
        calls.append((path,kwargs))
        if path.endswith('/access_tokens'): return {'token':'scoped-token'}
        return {'account':{'id':11}}
    monkeypatch.setattr(github,'api',api)
    token=github.installation_token({'installation_id':33,'repository_id':22,'github_user_id':11})
    assert token=='scoped-token'
    assert calls[-1][1]['body']=={'repository_ids':[22],'permissions':{'contents':'read'}}


def test_source_blobs_are_bound_to_git_hashes(context,monkeypatch):
    proof={'repository_id':22,'installation_id':33,'github_user_id':11,'github_login':'student','participant_id':'user','repo_name':'student/lab'}
    context[1]['GHAUTH#team']=proof
    monkeypatch.setattr(github,'installation_token',lambda _proof:'scoped')
    data=b'resource "aws_sqs_queue" "test" {}'
    sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    monkeypatch.setattr(github,'load_pack',lambda _: {'version':'1','missions':[{'id':'mission','evaluation':{'validator':'aws-event-driven-plan-v1','source_files':['main.tf'],'required_files':['main.tf']}}]})
    def api(path,**kwargs):
        assert kwargs['token']=='scoped'
        if '/git/commits/' in path: return {'sha':'a'*40,'tree':{'sha':'b'*40}}
        if '/git/trees/' in path: return {'sha':'b'*40,'tree':[{'path':'main.tf','sha':sha,'size':len(data),'mode':'100644','type':'blob'}]}
        if '/git/blobs/' in path: return {'encoding':'base64','content':base64.b64encode(data).decode()}
        return {'id':22,'full_name':'student/lab','owner':{'id':11}}
    monkeypatch.setattr(github,'api',api)
    item={'PK':'EVENT#event','repo_name':'student/lab','team_id':'team','commit_sha':'a'*40,'game_pack':'pack','pack_version':'1','mission_id':'mission'}
    result=github.verified_source(item)
    assert result['repository_verified'] is True
    assert result['files']['main.tf']==base64.b64encode(data).decode()
    assert 'scoped' not in json.dumps(result)
    # The same metadata with a forged blob body must be rejected.
    data=b'modified after hash'
    with pytest.raises(github.GitHubError): github.verified_source(item)


def test_app_jwt_uses_rsa_short_expiry():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    token=github.app_token({'app_id':123},pem)
    payload=jwt.decode(token,key.public_key(),algorithms=['RS256'])
    assert payload['iss']=='123'
    assert payload['exp']-payload['iat']<=600


def test_internal_source_endpoint_requires_worker_secret(context,monkeypatch,tmp_path):
    secret=tmp_path/'token';secret.write_text('worker-secret')
    monkeypatch.setattr(settings,'evaluation_runner_token_file',str(secret))
    path='/internal/evaluations/event/evaluation/source'
    assert context[2].post(path,json={'lease_token':'a'*32}).status_code==401
    response=context[2].post(path,json={'lease_token':'a'*32},headers={'Authorization':'Bearer worker-secret'})
    assert response.status_code==409


def test_unconfigured_app_blocks_execution_without_points(monkeypatch):
    monkeypatch.setattr(github,'get_item',lambda *_args:None)
    with pytest.raises(github.GitHubError):
        github.verified_source({'PK':'EVENT#event','team_id':'team','repo_name':'student/lab','commit_sha':'a'*40})


def test_oauth_code_and_state_are_redacted_from_access_logs():
    record=logging.LogRecord('uvicorn.access',20,'',0,'%s - "%s %s HTTP/%s" %s',('client','GET','/api/v1/github/callback?code=secret&state=private','1.1',303),None)
    assert main.OAuthAccessFilter().filter(record)
    assert 'secret' not in record.getMessage()
    assert 'private' not in record.getMessage()
