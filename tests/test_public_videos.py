from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.jobs as jobs_module
from app.job_service import JobService
from app.job_store import InMemoryJobStore
from app.main import app
from app.providers import MockVideoProvider


client = TestClient(app)
JOB_ID = "job_27b08bf70a034f07a8440280d8fd70f4"
FILENAME = f"{JOB_ID}.mp4"
PAYLOAD = b"fake-mp4-video-content"


@pytest.fixture
def public_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    path = output_dir / FILENAME
    path.write_bytes(PAYLOAD)
    provider = MockVideoProvider()
    service = JobService(
        store=InMemoryJobStore(),
        providers={"mock": provider, "veo": provider},
        models={"mock": "mock", "veo": "veo"},
        output_dir=output_dir,
    )
    monkeypatch.setattr(jobs_module, "job_service", service)
    return path


def test_public_video_is_inline_and_does_not_require_api_key(public_video: Path) -> None:
    response = client.get(f"/videos/{FILENAME}")

    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-disposition"] == f'inline; filename="{FILENAME}"'
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["access-control-allow-origin"] == "*"


def test_public_video_supports_byte_ranges(public_video: Path) -> None:
    response = client.get(f"/videos/{FILENAME}", headers={"Range": "bytes=0-3"})

    assert response.status_code == 206
    assert response.content == PAYLOAD[:4]
    assert response.headers["content-range"] == f"bytes 0-3/{len(PAYLOAD)}"
    assert response.headers["accept-ranges"] == "bytes"


def test_public_video_rejects_unsatisfiable_range(public_video: Path) -> None:
    response = client.get(f"/videos/{FILENAME}", headers={"Range": "bytes=999-1000"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(PAYLOAD)}"


def test_public_video_supports_head(public_video: Path) -> None:
    response = client.head(f"/videos/{FILENAME}")

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == str(len(PAYLOAD))
    assert response.headers["content-type"] == "video/mp4"


def test_public_video_returns_404_when_file_is_missing(public_video: Path) -> None:
    missing = "job_00000000000000000000000000000000.mp4"

    assert client.get(f"/videos/{missing}").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/videos/not-a-job.mp4",
        "/videos/job_27B08BF70A034F07A8440280D8FD70F4.mp4",
        "/videos/job_27b08bf70a034f07a8440280d8fd70f4.txt",
        "/videos/..%2FREADME.md",
        "/videos/%2e%2e%2FREADME.md",
        "/videos/job_27b08bf70a034f07a8440280d8fd70f4.mp4%5C..%5CREADME.md",
    ],
)
def test_public_video_rejects_invalid_names_and_traversal(public_video: Path, path: str) -> None:
    assert client.get(path).status_code == 404


def test_public_video_rejects_symlink_outside_outputs(
    public_video: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    public_video.unlink()
    public_video.symlink_to(outside)

    assert client.get(f"/videos/{FILENAME}").status_code == 404


def test_videos_root_does_not_list_directory(public_video: Path) -> None:
    response = client.get("/videos/")

    assert response.status_code == 404
    assert FILENAME not in response.text


def test_existing_authenticated_video_endpoint_is_unchanged(public_video: Path) -> None:
    assert client.get(f"/jobs/{JOB_ID}/video").status_code == 404
