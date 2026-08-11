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
        return ProviderOperation("operations/status-test", object())

    def poll(self, operation: ProviderOperation) -> PollResult:
        return PollResult(True, operation, b"fake-mp4")

    def download(self, video_handle: bytes, destination: Path) -> None:
        destination.write_bytes(video_handle)


@pytest.fixture
def status_jobs(
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


def test_post_job_status_returns_existing_job_without_calling_provider(
    status_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
) -> None:
    _, service, provider = status_jobs
    job = service.create(JobCreate(prompt="status lookup"))

    response = client.post(
        "/job-status",
        json={"job_id": job.job_id},
        headers={"X-API-Key": SERVER_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == job.job_id
    assert response.json()["status"] == "queued"
    assert provider.start_calls == 0


def test_post_job_status_missing_job_matches_get_error(status_jobs: object) -> None:
    headers = {"X-API-Key": SERVER_TOKEN}
    post_response = client.post(
        "/job-status",
        json={"job_id": "job_missing"},
        headers=headers,
    )
    get_response = client.get("/jobs/job_missing", headers=headers)

    assert post_response.status_code == get_response.status_code == 404
    assert post_response.json() == get_response.json() == {"detail": "Job not found"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-token"}])
def test_post_job_status_requires_api_key(
    status_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
    headers: dict[str, str],
) -> None:
    _, service, provider = status_jobs
    job = service.create(JobCreate(prompt="protected lookup"))

    response = client.post("/job-status", json={"job_id": job.job_id}, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API key"}
    assert provider.start_calls == 0


def test_post_job_status_requires_job_id(status_jobs: object) -> None:
    response = client.post(
        "/job-status",
        json={},
        headers={"X-API-Key": SERVER_TOKEN},
    )

    assert response.status_code == 422


def test_existing_get_job_status_behavior_is_unchanged(
    status_jobs: tuple[InMemoryJobStore, JobService, CountingProvider],
) -> None:
    _, service, provider = status_jobs
    job = service.create(JobCreate(prompt="existing get"))

    response = client.get(f"/jobs/{job.job_id}")

    assert response.status_code == 200
    assert response.json()["job_id"] == job.job_id
    assert provider.start_calls == 0
