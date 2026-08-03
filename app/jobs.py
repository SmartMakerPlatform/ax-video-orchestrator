from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from fastapi.responses import FileResponse

from app.auth import require_api_key
from app.config import load_settings
from app.job_models import JobCreate, JobCreateResponse, JobDetail, JobStatus
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


def authorize_if_veo(provider: str, api_key: str | None) -> None:
    if provider == "veo":
        require_api_key(api_key, settings.orchestrator_api_key)


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
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    authorize_if_veo(job.provider, x_api_key)
    return JobDetail.model_validate(job.model_dump())


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
