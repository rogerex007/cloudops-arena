"""A dedicated browser route must not replace server-side authorization."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.security import create_token

ROUTES=[
    ('GET','/api/v1/admin/dashboard',None),
    ('GET','/api/v1/admin/game-packs',None),
    ('GET','/api/v1/admin/lab-providers/health',None),
    ('POST','/api/v1/admin/events',{'title':'Protected event'}),
    ('PATCH','/api/v1/admin/events/test/status',{'status':'open'}),
    ('POST','/api/v1/admin/events/test/activate-mission',{'mission_id':'mission-01'}),
    ('PATCH','/api/v1/admin/events/test/teams/test/github',{'repo_name':'example/lab','repo_url':'https://github.com/example/lab'}),
    ('POST','/api/v1/admin/demo/award',{'event_id':'test','team_id':'test','mission_id':'mission-02'}),
]


@pytest.mark.parametrize('method,path,body',ROUTES)
def test_administrative_operations_require_authenticated_admin(method,path,body):
    client=TestClient(app)
    assert client.request(method,path,json=body).status_code==401
    token=create_token({'sub':'test','role':'participant','event_id':'test','team_id':'test'})
    response=client.request(method,path,json=body,headers={'Authorization':'Bearer '+token})
    assert response.status_code==403


def test_bearer_token_cannot_replace_instructor_login_credentials():
    token=create_token({'sub':'test','role':'participant'})
    response=TestClient(app).post('/api/v1/auth/admin/login',json={'username':'invalid-test-user','password':'invalid-test-password'},headers={'Authorization':'Bearer '+token})
    assert response.status_code==401
