from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from google import genai
from google.genai import errors, types


class ProviderError(Exception):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


@dataclass(frozen=True)
class ProviderOperation:
    name: str
    handle: Any


@dataclass(frozen=True)
class PollResult:
    done: bool
    operation: ProviderOperation
    video_handle: Any | None = None


class VideoProvider(Protocol):
    def start(self, prompt: str, model: str) -> ProviderOperation: ...
    def poll(self, operation: ProviderOperation) -> PollResult: ...
    def download(self, video_handle: Any, destination: Path) -> None: ...


class MockVideoProvider:
    def start(self, prompt: str, model: str) -> ProviderOperation:
        name = f"mock/{uuid4().hex}"
        return ProviderOperation(name, name)

    def poll(self, operation: ProviderOperation) -> PollResult:
        return PollResult(True, operation, b"mock-mp4")

    def download(self, video_handle: Any, destination: Path) -> None:
        destination.write_bytes(video_handle)


def build_veo_config() -> types.GenerateVideosConfig:
    return types.GenerateVideosConfig(
        number_of_videos=1,
        resolution="720p",
        aspect_ratio="16:9",
        duration_seconds=8,
    )


class GoogleVeoProvider:
    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise ProviderError("api_key_missing", "Video provider is not configured")
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def start(self, prompt: str, model: str) -> ProviderOperation:
        try:
            operation = self._get_client().models.generate_videos(
                model=model,
                prompt=prompt,
                config=build_veo_config(),
            )
            return ProviderOperation(operation.name or "", operation)
        except ProviderError:
            raise
        except errors.APIError as exc:
            raise self._normalize_api_error(exc) from None
        except Exception:
            raise ProviderError("provider_error", "Video generation could not be started") from None

    def poll(self, operation: ProviderOperation) -> PollResult:
        try:
            current = self._get_client().operations.get(operation.handle)
            wrapped = ProviderOperation(current.name or operation.name, current)
            if not current.done:
                return PollResult(False, wrapped)
            if current.error:
                raise ProviderError("provider_error", "Video generation failed")
            response = current.response
            videos = response.generated_videos if response else None
            if not videos or not videos[0].video:
                raise ProviderError("result_missing", "The provider returned no video")
            return PollResult(True, wrapped, videos[0].video)
        except ProviderError:
            raise
        except errors.APIError as exc:
            raise self._normalize_api_error(exc) from None
        except Exception:
            raise ProviderError("provider_error", "Video generation status could not be checked") from None

    def download(self, video_handle: Any, destination: Path) -> None:
        try:
            content = self._get_client().files.download(file=video_handle)
            if not content:
                raise ProviderError("result_missing", "The provider returned no video")
            destination.write_bytes(content)
        except ProviderError:
            raise
        except errors.APIError as exc:
            raise self._normalize_api_error(exc) from None
        except OSError:
            raise
        except Exception:
            raise ProviderError("download_failed", "The generated video could not be downloaded") from None

    @staticmethod
    def _normalize_api_error(exc: errors.APIError) -> ProviderError:
        status_code = getattr(exc, "code", None)
        message = str(getattr(exc, "message", "")).lower()
        if status_code in (401, 403):
            return ProviderError("authentication_failed", "Video provider authentication failed")
        if status_code == 429:
            return ProviderError("quota_exceeded", "Video provider quota or billing limit was reached")
        if status_code == 400 and any(word in message for word in ("safety", "policy", "blocked")):
            return ProviderError("safety_rejected", "The prompt was rejected by the content policy")
        if status_code in (408, 500, 502, 503, 504):
            return ProviderError("provider_unavailable", "The video provider is temporarily unavailable")
        return ProviderError("provider_error", "The video provider rejected the request")
