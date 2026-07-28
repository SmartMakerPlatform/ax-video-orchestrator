from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

router = APIRouter()


class JobCreate(BaseModel):
    prompt: str = Field(max_length=2000)
    provider: Literal["mock"] = "mock"

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be empty")
        return value


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued"]


class MockJob(JobResponse):
    prompt: str
    provider: Literal["mock"]


mock_jobs: dict[str, MockJob] = {}


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(request: JobCreate) -> JobResponse:
    job_id = f"job_{uuid4().hex}"
    job = MockJob(
        job_id=job_id,
        status="queued",
        prompt=request.prompt,
        provider=request.provider,
    )
    mock_jobs[job_id] = job
    return JobResponse(job_id=job.job_id, status=job.status)
