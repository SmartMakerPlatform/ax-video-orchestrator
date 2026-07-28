from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_job() -> None:
    request = {
        "prompt": "아이와 강아지가 여름 바닷가를 달리는 영상",
        "provider": "mock",
    }

    first_response = client.post("/jobs", json=request)
    second_response = client.post("/jobs", json=request)

    assert first_response.status_code == 201
    assert first_response.json()["job_id"].startswith("job_")
    assert first_response.json()["status"] == "queued"
    assert second_response.status_code == 201
    assert first_response.json()["job_id"] != second_response.json()["job_id"]


def test_create_job_uses_mock_provider_by_default() -> None:
    response = client.post("/jobs", json={"prompt": "테스트 영상"})

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


def test_create_job_rejects_invalid_prompt() -> None:
    for prompt in ("", "   ", "a" * 2001):
        response = client.post("/jobs", json={"prompt": prompt})

        assert response.status_code == 422


def test_create_job_rejects_unsupported_provider() -> None:
    response = client.post(
        "/jobs",
        json={"prompt": "테스트 영상", "provider": "veo"},
    )

    assert response.status_code == 422
