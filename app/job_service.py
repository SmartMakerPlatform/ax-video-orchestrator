import asyncio
import os
from pathlib import Path
from uuid import uuid4

from app.job_models import JobCreate, JobRecord, JobStatus, utc_now
from app.job_store import InMemoryJobStore
from app.providers import ProviderError, VideoProvider


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"


class ActiveVeoJobError(Exception):
    pass


class JobService:
    def __init__(
        self,
        store: InMemoryJobStore,
        providers: dict[str, VideoProvider],
        models: dict[str, str],
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        poll_interval_seconds: float = 10,
        timeout_seconds: float = 15 * 60,
    ) -> None:
        self.store = store
        self.providers = providers
        self.models = models
        self.output_dir = output_dir.resolve()
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    def create(self, request: JobCreate) -> JobRecord:
        now = utc_now()
        job = JobRecord(
            job_id=f"job_{uuid4().hex}",
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            prompt=request.prompt,
            provider=request.provider,
            model=self.models[request.provider],
        )
        if request.provider == "veo":
            created = self.store.create_if_no_active_veo(job)
            if created is None:
                raise ActiveVeoJobError
            return created
        return self.store.create(job)

    async def process(self, job_id: str) -> None:
        if self.store.get(job_id) is None:
            return
        self.store.update(job_id, status=JobStatus.PROCESSING, updated_at=utc_now())
        try:
            await asyncio.wait_for(self._run_provider(job_id), self.timeout_seconds)
        except TimeoutError:
            self._fail(job_id, "timeout", "Video generation timed out")
        except ProviderError as exc:
            self._fail(job_id, exc.code, exc.public_message)
        except OSError:
            self._fail(job_id, "file_save_failed", "The generated video could not be saved")
        except Exception:
            self._fail(job_id, "internal_error", "Video generation failed")

    async def _run_provider(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        provider = self.providers[job.provider]
        operation = await asyncio.to_thread(provider.start, job.prompt, job.model)
        self.store.update(
            job_id,
            operation_name=operation.name or None,
            updated_at=utc_now(),
        )
        while True:
            result = await asyncio.to_thread(provider.poll, operation)
            operation = result.operation
            if result.done:
                break
            await asyncio.sleep(self.poll_interval_seconds)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.output_dir / f"{job_id}.mp4"
        temporary_path = self.output_dir / f"{job_id}.mp4.part"
        try:
            await asyncio.to_thread(provider.download, result.video_handle, temporary_path)
            await asyncio.to_thread(os.replace, temporary_path, final_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        self.store.update(
            job_id,
            status=JobStatus.COMPLETED,
            updated_at=utc_now(),
            operation_name=operation.name or None,
            result_url=f"/jobs/{job_id}/video",
            result_path=str(final_path),
            error_code=None,
            error_message=None,
        )

    def _fail(self, job_id: str, code: str, message: str) -> None:
        self.store.update(
            job_id,
            status=JobStatus.FAILED,
            updated_at=utc_now(),
            error_code=code,
            error_message=message,
        )

    def video_path(self, job_id: str) -> Path | None:
        job = self.store.get(job_id)
        if not job or not job.result_path:
            return None
        path = Path(job.result_path).resolve()
        if path.parent != self.output_dir or path.name != f"{job_id}.mp4":
            return None
        return path
