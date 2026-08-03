from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.jobs as jobs_module
from app.config import Settings
from app.job_models import JobCreate
from app.job_service import JobService
from app.job_store import InMemoryJobStore
from app.main import app
from app.providers import PollResult, ProviderOperation


client = TestClient(app)
SERVER_TOKEN = "test-orchestrator-token-not-a-real-secret"


class CountingProvider:
    def __init__(self) -> None:
        self.start_calls = 0

    def start(self, prompt: str, model: str) -> ProviderOperation:
        self.start_calls += 1
        return ProviderOperation("operations/auth-test", object())

    def poll(self, operation: ProviderOperation) -> PollResult:
        return PollResult(True, operation, b"fake-mp4")

    def download(self, video_handle: bytes, destination: Path) -> None:
        destination.write_bytes(video_handle)


@pytest.fixture
def secured_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[InMemoryJobStore, JobService, CountingProvider]:
    store = InMemoryJobStore()
    provider = CountingProvider()
    service = JobService(
        store=store,
        providers={"mock": provider, "veo": provider},
        models={"mock": "mock", "veo": "veo-3.1-lite-generate-preview"},
        output_dir=tmp_path / "outputs",
        poll_interval_seconds=0,
        timeout_seconds=1,
    )
    monkeypatch.setattr(jobs_module, "job_store", store)
    monkeypatch.setattr(jobs_module, "job_service", service)
    monkeypatch.setattr(
        jobs_module,
        "settings",
        Settings(
            gemini_api_key=None,
            orchestrator_api_key=SERVER_TOKEN,
            veo_model="veo-3.1-lite-generate-preview",
        ),
    )
    return store, service, provider


def test_mock_request_stays_public(secured_jobs: object) -> None:
    response = client.post("/jobs", json={"prompt": "public mock"})
    assert response.status_code == 201
    assert response.json()["status"] == "queued"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-token"}])
def test_veo_rejects_missing_or_wrong_key(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
    headers: dict[str, str],
) -> None:
    store, _, provider = secured_jobs
    response = client.post(
        "/jobs",
        json={"prompt": "paid request", "provider": "veo"},
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API key"}
    assert provider.start_calls == 0
    assert store._jobs == {}


def test_veo_accepts_only_the_correct_key(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
) -> None:
    _, _, provider = secured_jobs
    response = client.post(
        "/jobs",
        json={"prompt": "authorized", "provider": "veo"},
        headers={"X-API-Key": SERVER_TOKEN},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    assert provider.start_calls == 1


def test_veo_rejects_when_server_token_is_unset(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, provider = secured_jobs
    monkeypatch.setattr(
        jobs_module,
        "settings",
        Settings(None, None, "veo-3.1-lite-generate-preview"),
    )
    response = client.post(
        "/jobs",
        json={"prompt": "no server token", "provider": "veo"},
        headers={"X-API-Key": SERVER_TOKEN},
    )
    assert response.status_code == 401
    assert provider.start_calls == 0
    assert store._jobs == {}


def test_second_active_veo_job_is_rejected(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
) -> None:
    _, service, provider = secured_jobs
    service.create(JobCreate(prompt="first", provider="veo"))
    response = client.post(
        "/jobs",
        json={"prompt": "second", "provider": "veo"},
        headers={"X-API-Key": SERVER_TOKEN},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "A Veo job is already active"}
    assert provider.start_calls == 0


def test_veo_status_and_video_require_the_same_key(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
) -> None:
    _, service, _ = secured_jobs
    job = service.create(JobCreate(prompt="private result", provider="veo"))
    assert client.get(f"/jobs/{job.job_id}").status_code == 401
    assert client.get(f"/jobs/{job.job_id}/video").status_code == 401
    status_response = client.get(
        f"/jobs/{job.job_id}",
        headers={"X-API-Key": SERVER_TOKEN},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"


def test_auth_token_is_absent_from_response_and_logs(
    secured_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.post(
        "/jobs",
        json={"prompt": "private", "provider": "veo"},
        headers={"X-API-Key": SERVER_TOKEN},
    )
    assert response.status_code == 201
    assert SERVER_TOKEN not in response.text
    assert SERVER_TOKEN not in caplog.text
