"""Access-control regression tests. Run: python -m pytest -q test_app.py"""
import os
from unittest.mock import patch

os.environ["ALLOWED_TAILSCALE_USERS"] = "runner@example.com"
from fastapi.testclient import TestClient  # noqa: E402
from app import app, jobs  # noqa: E402

HEADERS = {"Tailscale-User-Login": "runner@example.com"}
URL = "https://open.spotify.com/track/" + "a" * 22


def test_health_is_accessible_without_identity():
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200


def test_missing_or_unknown_identity_denied():
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 403
        assert client.get("/api/jobs", headers={"Tailscale-User-Login": "other@example.com"}).status_code == 403


def test_only_owner_sees_jobs():
    jobs.clear()
    jobs["known"] = {"id": "known", "owner": "runner@example.com", "url": URL, "status": "completed",
                     "created": "", "updated": "", "return_code": 0, "logs": []}
    jobs["hidden"] = {**jobs["known"], "id": "hidden", "owner": "other@example.com"}
    with TestClient(app) as client:
        response = client.get("/api/jobs", headers=HEADERS)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["known"]
    jobs.clear()


def test_rejects_cross_site_and_wrong_content_type():
    with TestClient(app) as client:
        assert client.post("/api/jobs", headers={**HEADERS, "Origin": "https://evil.example",
                                                  "Content-Type": "application/json"}, json={"url": URL}).status_code == 403
        assert client.post("/api/jobs", headers={**HEADERS, "Content-Type": "text/plain"}, content="{}").status_code == 415


def test_queue_requires_disk_space():
    jobs.clear()
    with TestClient(app) as client:
        with patch("app.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            response = client.post("/api/jobs", headers=HEADERS, json={"url": URL})
            assert response.status_code == 507
    jobs.clear()
