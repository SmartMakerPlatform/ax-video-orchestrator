import asyncio
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import app.jobs as jobs_module
from app.job_models import JobCreate, JobStatus
from app.job_service import JobService
from app.job_store import InMemoryJobStore
from app.main import app
from app.providers import GoogleVeoProvider, PollResult, ProviderError, ProviderOperation

client = TestClient(app)

class FakeProvider:
    def __init__(self, payload: bytes = b"fake-mp4", failure: ProviderError | None = None,
                 observed_store: InMemoryJobStore | None = None, observed_job_id: str | None = None) -> None:
        self.payload = payload
        self.failure = failure
        self.observed_store = observed_store
        self.observed_job_id = observed_job_id

    def start(self, prompt: str, model: str) -> ProviderOperation:
        if self.observed_store and self.observed_job_id:
            assert self.observed_store.get(self.observed_job_id).status == JobStatus.PROCESSING
        if self.failure:
            raise self.failure
        return ProviderOperation("operations/fake", object())

    def poll(self, operation: ProviderOperation) -> PollResult:
        return PollResult(True, operation, self.payload)

    def download(self, video_handle: bytes, destination: Path) -> None:
        destination.write_bytes(video_handle)

def make_service(tmp_path: Path, provider: object | None = None) -> tuple[InMemoryJobStore, JobService]:
    store = InMemoryJobStore()
    service = JobService(
        store=store,
        providers={"mock": provider or FakeProvider(), "veo": provider or FakeProvider()},
        models={"mock": "mock", "veo": "veo-3.1-lite-generate-preview"},
        output_dir=tmp_path / "outputs",
        poll_interval_seconds=0,
        timeout_seconds=1,
    )
    return store, service

def test_create_job_preserves_existing_response_contract() -> None:
    request = {"prompt": "아이와 강아지가 여름 바닷가를 달리는 영상", "provider": "mock"}
    first = client.post("/jobs", json=request)
    second = client.post("/jobs", json=request)
    assert first.status_code == 201
    assert set(first.json()) == {"job_id", "status"}
    assert first.json()["job_id"].startswith("job_")
    assert first.json()["status"] == "queued"
    assert first.json()["job_id"] != second.json()["job_id"]

def test_create_job_uses_mock_provider_by_default() -> None:
    response = client.post("/jobs", json={"prompt": "테스트 영상"})
    assert response.status_code == 201
    assert response.json()["status"] == "queued"

@pytest.mark.parametrize("prompt", ["", "   ", "a" * 2001])
def test_create_job_rejects_invalid_prompt(prompt: str) -> None:
    assert client.post("/jobs", json={"prompt": prompt}).status_code == 422

def test_create_job_rejects_unsupported_provider() -> None:
    assert client.post("/jobs", json={"prompt": "테스트", "provider": "kling"}).status_code == 422

def test_post_schedules_background_work_without_awaiting_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, service = make_service(tmp_path)
    monkeypatch.setattr(jobs_module, "job_store", store)
    monkeypatch.setattr(jobs_module, "job_service", service)
    tasks = BackgroundTasks()
    response = asyncio.run(jobs_module.create_job(JobCreate(prompt="quick response"), tasks))
    assert response.status == JobStatus.QUEUED
    assert store.get(response.job_id).status == JobStatus.QUEUED
    assert len(tasks.tasks) == 1

def test_job_transitions_processing_to_completed(tmp_path: Path) -> None:
    store, service = make_service(tmp_path)
    job = service.create(JobCreate(prompt="success", provider="veo"))
    provider = FakeProvider(observed_store=store, observed_job_id=job.job_id)
    service.providers["veo"] = provider
    asyncio.run(service.process(job.job_id))
    completed = store.get(job.job_id)
    assert completed.status == JobStatus.COMPLETED
    assert completed.operation_name == "operations/fake"
    assert completed.result_url == f"/jobs/{job.job_id}/video"
    assert Path(completed.result_path).read_bytes() == b"fake-mp4"

def test_missing_api_key_fails_safely(tmp_path: Path) -> None:
    store, service = make_service(tmp_path, GoogleVeoProvider(None))
    job = service.create(JobCreate(prompt="no key", provider="veo"))
    asyncio.run(service.process(job.job_id))
    failed = store.get(job.job_id)
    assert failed.status == JobStatus.FAILED
    assert failed.error_code == "api_key_missing"
    assert failed.error_message == "Video provider is not configured"

def test_provider_failure_is_sanitized(tmp_path: Path) -> None:
    failure = ProviderError("quota_exceeded", "Video provider quota or billing limit was reached")
    store, service = make_service(tmp_path, FakeProvider(failure=failure))
    job = service.create(JobCreate(prompt="failure", provider="veo"))
    asyncio.run(service.process(job.job_id))
    failed = store.get(job.job_id)
    assert failed.status == JobStatus.FAILED
    assert failed.error_code == "quota_exceeded"
    assert "secret" not in failed.model_dump_json().lower()

def test_status_and_video_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, service = make_service(tmp_path)
    monkeypatch.setattr(jobs_module, "job_store", store)
    monkeypatch.setattr(jobs_module, "job_service", service)
    job = service.create(JobCreate(prompt="download"))
    pending = client.get(f"/jobs/{job.job_id}/video")
    assert pending.status_code == 409
    asyncio.run(service.process(job.job_id))
    status_response = client.get(f"/jobs/{job.job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["result_url"] == f"/jobs/{job.job_id}/video"
    video = client.get(f"/jobs/{job.job_id}/video")
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert video.content == b"fake-mp4"

def test_video_path_rejects_an_unexpected_file(tmp_path: Path) -> None:
    store, service = make_service(tmp_path)
    job = service.create(JobCreate(prompt="unsafe"))
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    store.update(job.job_id, status=JobStatus.COMPLETED, result_path=str(outside))
    assert service.video_path(job.job_id) is None
