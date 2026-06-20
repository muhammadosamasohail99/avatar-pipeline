from fastapi.testclient import TestClient
from main import app

def test_dashboard():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "Avatar Pipeline" in r.text

def test_health():
    c = TestClient(app)
    r = c.get("/health")
    assert r.json() == {"ok": True}
