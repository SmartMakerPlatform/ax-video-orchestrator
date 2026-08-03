# ax-video-orchestrator

스마트메이커의 영상 생성 요청을 받아 Google Veo 작업을 비동기로 조율하는 FastAPI PoC입니다. 현재 운영 구성은 AWS Lightsail Ubuntu 24.04, Uvicorn(`127.0.0.1:8000`), Caddy HTTPS 역방향 프록시입니다.

## 처리 흐름

```text
스마트메이커 → POST /jobs → FastAPI가 job_id/queued 즉시 반환
                              ↓ 백그라운드
                         Google Veo operation
                              ↓ 상태 폴링
                         outputs/{job_id}.mp4
```

`provider`를 생략하면 기존 호환 동작인 `mock`이 사용됩니다. 실제 Veo는 `provider: "veo"`를 명시한 요청에서만 선택됩니다.

## API

- `GET /health`: `{"status":"ok"}`
- `POST /jobs`: 작업 접수. 기존 응답 계약인 `job_id`, `status: queued`를 유지합니다.
- `GET /jobs/{job_id}`: queued, processing, completed, failed 상태와 공개 가능한 작업 정보를 조회합니다.
- `GET /jobs/{job_id}/video`: 완료된 MP4를 내려받습니다. 완료 전에는 HTTP 409를 반환합니다.

Mock 작업은 인증 없이 기존처럼 호출할 수 있습니다.

```json
{
  "prompt": "아이와 강아지가 여름 바닷가를 달리는 영상",
  "provider": "mock"
}
```

Veo 작업의 생성·상태 조회·영상 다운로드에는 `X-API-Key` 헤더가 필요합니다. 토큰이 서버에 설정되지 않았거나 일치하지 않으면 HTTP 401을 반환하며 작업을 생성하지 않습니다. queued 또는 processing 상태인 Veo 작업은 한 번에 하나만 허용됩니다.

```text
X-API-Key: <ORCHESTRATOR_API_KEY>
```

## 환경변수

`.env.example`을 참고하십시오. 실제 비밀값은 Git에 추가하지 않은 환경 파일 또는 서비스 환경으로 전달해야 합니다.

```text
GEMINI_API_KEY=replace-with-your-key
ORCHESTRATOR_API_KEY=replace-with-a-long-random-token
VEO_MODEL=veo-3.1-lite-generate-preview
```

`ORCHESTRATOR_API_KEY`는 클라이언트가 유료 Veo 요청을 호출하기 위한 서버 전용 인증 토큰이며 Google의 `GEMINI_API_KEY`와 별개입니다. `VEO_MODEL`이 없으면 `veo-3.1-lite-generate-preview`가 기본값입니다. `GEMINI_API_KEY`가 없으면 인증된 Veo 작업도 안전하게 `failed`가 되며 키 자체는 응답에 포함되지 않습니다.

## 로컬 설치 및 Mock 테스트

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

테스트는 Fake 공급자를 사용하며 Google API를 호출하지 않아 과금되지 않습니다. 실제 `provider: "veo"` 요청은 Google API 사용료가 발생할 수 있습니다.

## 출력과 현재 PoC 제약

- 생성 영상은 Git에서 제외된 `outputs/{job_id}.mp4`에 저장됩니다.
- 작업 상태는 프로세스 메모리에만 저장되므로 서비스 재시작 시 사라집니다.
- 재시작 시 실행 중인 백그라운드 작업도 중단되며 자동 복구되지 않습니다.
- Redis, Celery, 데이터베이스 및 영구 작업 큐는 아직 사용하지 않습니다.
- 현재 인증은 하나의 공유 토큰을 사용하는 최소 PoC 방식이며 사용자별 권한, 토큰 회전, 요청 속도 제한은 아직 없습니다.

비밀키, API 키, 토큰은 소스, README, 로그 또는 Git 추적 파일에 기록하지 마십시오. 자세한 작업 원칙은 `AGENTS.md`를 따릅니다.
