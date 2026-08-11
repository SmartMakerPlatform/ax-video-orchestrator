from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class JobCreate(BaseModel):
    prompt: str = Field(max_length=2000)
    provider: Literal["mock", "veo"] = "mock"

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be empty")
        return value

class JobCreateResponse(BaseModel):
    job_id: str
    status: Literal[JobStatus.QUEUED]

class JobStatusRequest(BaseModel):
    job_id: str

class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    provider: str
    model: str
    operation_name: str | None = None
    result_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None

class JobRecord(JobDetail):
    prompt: str
    result_path: str | None = None

def utc_now() -> datetime:
    return datetime.now(timezone.utc)
