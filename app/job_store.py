from threading import Lock

from app.job_models import JobRecord, JobStatus


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create(self, job: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[job.job_id] = job.model_copy(deep=True)
            return job.model_copy(deep=True)

    def create_if_no_active_veo(self, job: JobRecord) -> JobRecord | None:
        with self._lock:
            has_active_veo = any(
                existing.provider == "veo"
                and existing.status in (JobStatus.QUEUED, JobStatus.PROCESSING)
                for existing in self._jobs.values()
            )
            if has_active_veo:
                return None
            self._jobs[job.job_id] = job.model_copy(deep=True)
            return job.model_copy(deep=True)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def update(self, job_id: str, **changes: object) -> JobRecord:
        with self._lock:
            updated = self._jobs[job_id].model_copy(update=changes, deep=True)
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)
