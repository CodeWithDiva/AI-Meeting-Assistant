from fastapi.testclient import TestClient

from app.main import app


def test_simulated_agent_lifecycle() -> None:
    client = TestClient(app)
    client.post("/api/agent/stop")

    start = client.post("/api/agent/start", json={"meeting_id": 123})
    assert start.status_code == 200
    assert start.json() == {
        "state": "listening",
        "mode": "simulated",
        "meeting_id": 123,
    }

    duplicate = client.post("/api/agent/start", json={"meeting_id": 456})
    assert duplicate.status_code == 409

    stop = client.post("/api/agent/stop")
    assert stop.status_code == 200
    assert stop.json() == {
        "state": "stopped",
        "mode": "simulated",
        "meeting_id": None,
    }