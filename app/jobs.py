import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from fastapi.responses import FileResponse

from app.auth import require_api_key
from app.config import load_settings
from app.job_models import JobCreate, JobCreateResponse, JobDetail, JobStatus, JobStatusRequest
from app.job_service import ActiveVeoJobError, JobService
from app.job_store import InMemoryJobStore
from app.providers import GoogleVeoProvider, MockVideoProvider


router = APIRouter()
settings = load_settings()
job_store = InMemoryJobStore()
job_service = JobService(
    store=job_store,
    providers={
        "mock": MockVideoProvider(),
        "veo": GoogleVeoProvider(settings.gemini_api_key),
    },
    models={"mock": "mock", "veo": settings.veo_model},
)
ApiKeyHeader = Annotated[str | None, Header(alias="X-API-Key")]
VIDEO_FILENAME_PATTERN = re.compile(r"^job_[0-9a-f]{32}\.mp4$")


def authorize_if_veo(provider: str, api_key: str | None) -> None:
    if provider == "veo":
        require_api_key(api_key, settings.orchestrator_api_key)


def get_job_detail(job_id: str, api_key: str | None) -> JobDetail:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    authorize_if_veo(job.provider, api_key)
    return JobDetail.model_validate(job.model_dump())


def get_public_video_path(filename: str) -> Path | None:
    if VIDEO_FILENAME_PATTERN.fullmatch(filename) is None:
        return None

    candidate = job_service.output_dir / filename
    if candidate.is_symlink():
        return None

    try:
        path = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None

    if path.parent != job_service.output_dir or not path.is_file():
        return None
    return path


@router.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: JobCreate,
    background_tasks: BackgroundTasks,
    x_api_key: ApiKeyHeader = None,
) -> JobCreateResponse:
    authorize_if_veo(request.provider, x_api_key)
    try:
        job = job_service.create(request)
    except ActiveVeoJobError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Veo job is already active",
        ) from None
    background_tasks.add_task(job_service.process, job.job_id)
    return JobCreateResponse(job_id=job.job_id, status=JobStatus.QUEUED)


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, x_api_key: ApiKeyHeader = None) -> JobDetail:
    return get_job_detail(job_id, x_api_key)


@router.post("/job-status", response_model=JobDetail)
async def post_job_status(
    request: JobStatusRequest,
    x_api_key: ApiKeyHeader = None,
) -> JobDetail:
    require_api_key(x_api_key, settings.orchestrator_api_key)
    return get_job_detail(request.job_id, x_api_key)


@router.get("/jobs/{job_id}/video", response_class=FileResponse)
async def get_job_video(job_id: str, x_api_key: ApiKeyHeader = None) -> FileResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    authorize_if_veo(job.provider, x_api_key)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Video is not ready")
    path = job_service.video_path(job_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")

@router.api_route("/videos/{filename}", methods=["GET", "HEAD"], response_class=FileResponse)
async def get_public_video(filename: str) -> FileResponse:
    path = get_public_video_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename,
        content_disposition_type="inline",
        headers={"Access-Control-Allow-Origin": "*"},
    )
