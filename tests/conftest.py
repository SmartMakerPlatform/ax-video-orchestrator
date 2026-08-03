from pathlib import Path

import pytest

import app.jobs as jobs_module
from app.job_service import JobService
from app.job_store import InMemoryJobStore
from app.providers import MockVideoProvider


@pytest.fixture(autouse=True)
def isolate_legacy_job_tests(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not request.module.__name__.endswith("test_jobs"):
        return
    store = InMemoryJobStore()
    provider = MockVideoProvider()
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
