# ax-video-orchestrator

SmartMaker의 영상 생성 요청을 받아 Google Veo 작업을 비동기로 조율하고, 완성된 MP4를 HTTPS로 제공하는 FastAPI PoC입니다.

현재 운영 기준은 Ubuntu 24.04 LTS, Python 3.12, Uvicorn(127.0.0.1:8000)과 Caddy HTTPS 역방향 프록시입니다.

## 구조와 처리 흐름

~~~text
SmartMaker
  ├─ POST /jobs                 작업 생성
  ├─ POST /job-status           고정 경로 상태 조회
  └─ GET /videos/{job_id}.mp4   공개 MP4 재생
             │
             ▼
FastAPI / Uvicorn (127.0.0.1:8000)
             │ 비동기 Google operation 폴링
             ▼
Google Veo ──완료──> outputs/{job_id}.mp4
             ▲
             │
Caddy (80/443, HTTPS reverse proxy)
~~~

FastAPI는 요청 검증, 인증, 작업 상태, Veo 호출과 MP4 제공을 담당합니다. Caddy는 TLS 인증서와 외부 HTTPS 연결만 담당하며 outputs를 직접 공개하지 않습니다.

## API

- GET /health: 공개 상태 확인
- POST /jobs: 작업 생성. job_id와 status: queued를 즉시 반환
- GET /jobs/{job_id}: 작업 상태 조회
- POST /job-status: SmartMaker용 고정 경로 상태 조회
- GET /jobs/{job_id}/video: 기존 작업 기반 MP4 조회
- GET|HEAD /videos/{filename}: 공개 MP4 재생 및 Range 요청

provider를 생략하면 mock이 사용됩니다. 실제 유료 Veo 호출은 provider: veo일 때만 발생합니다.

Veo 작업 생성과 보호된 상태·영상 API에는 다음 헤더가 필요합니다.

~~~text
X-API-Key: <ORCHESTRATOR_API_KEY>
~~~

키가 없거나 틀리면 HTTP 401을 반환하며 Veo 작업을 만들지 않습니다. 활성 Veo 작업은 한 번에 하나만 허용됩니다.

### 공개 영상 URL

~~~text
https://<운영 도메인>/videos/{job_id}.mp4
~~~

예:

~~~text
https://ax-video-orchestrator.duckdns.org/videos/job_27b08bf70a034f07a8440280d8fd70f4.mp4
~~~

공개 경로는 API 키 없이 재생할 수 있고 Content-Type: video/mp4, inline disposition, CORS, HEAD와 byte Range(206)를 지원합니다. 파일명은 job_ 뒤 소문자 16진수 32자리만 허용하며, 경로 조작과 심볼릭 링크를 거부하고 반드시 outputs 내부의 일반 파일만 반환합니다. 디렉터리 목록은 제공하지 않습니다.

이 URL은 사실상 공유 링크입니다. URL을 아는 사람은 영상을 볼 수 있으므로 개인정보가 포함된 영상에는 별도의 만료 URL 또는 접근 제어가 필요합니다.

## 요구 환경

- Ubuntu 24.04 LTS 또는 동등한 Linux
- Python 3.12
- python3.12-venv, Git, curl
- Caddy stable 패키지
- 외부 HTTPS 운영 시 도메인과 TCP 80/443
- Google Veo 사용 시 Gemini Developer API 접근 및 결제 설정

FFmpeg는 애플리케이션 실행에 필요하지 않습니다. ffprobe는 영상 기술 검증을 위한 선택 도구입니다.

Python 의존성은 requirements.txt의 호환 범위로 관리됩니다. 현재 검증 환경은 FastAPI 0.140.7, Starlette 1.3.1, Uvicorn 0.51.0, google-genai 1.75.0입니다. 범위 설치는 향후 호환 버전을 선택할 수 있으므로 완전한 비트 단위 재현이 필요하면 배포 시점의 별도 lock 파일을 보존하십시오.

## 새 Ubuntu 서버 설치

### 1. 저장소와 Python 환경

~~~bash
git clone https://github.com/SmartMakerPlatform/ax-video-orchestrator.git
cd ax-video-orchestrator

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
install -d -m 750 outputs
.venv/bin/python -m pytest -q
~~~

비공개 저장소이므로 새 서버에는 GitHub 인증이 별도로 필요합니다.

운영 예시는 /home/ubuntu/ax-video-orchestrator를 사용합니다. 다른 사용자나 경로를 사용한다면 systemd 예시의 User, Group, WorkingDirectory, ExecStart를 함께 변경하십시오.

### 2. 환경변수

.env.example은 변수명만 제공하며 실제 키를 포함하지 않습니다. 운영 키는 Git 저장소 밖의 root 전용 파일에 둡니다.

~~~bash
sudo install -o root -g root -m 600 /dev/null /etc/ax-video-orchestrator.env
sudoedit /etc/ax-video-orchestrator.env
~~~

파일 형식:

~~~text
GEMINI_API_KEY=<실제 Google API 키>
ORCHESTRATOR_API_KEY=<충분히 긴 무작위 호출 토큰>
VEO_MODEL=veo-3.1-lite-generate-preview
~~~

키를 셸 명령 인자, Git, 채팅, 로그에 입력하지 마십시오.

### 3. 출력 디렉터리

~~~bash
sudo install -d -o ubuntu -g ubuntu -m 750 /home/ubuntu/ax-video-orchestrator/outputs
~~~

MP4와 .mp4.part는 Git에서 제외됩니다. outputs/.gitkeep만 디렉터리 구조 보존용으로 추적합니다.

### 4. systemd

예시는 deploy/systemd/ax-video-orchestrator.service와 deploy/systemd/environment.conf에 있습니다.

~~~bash
sudo install -o root -g root -m 644 deploy/systemd/ax-video-orchestrator.service /etc/systemd/system/ax-video-orchestrator.service

sudo install -d -o root -g root -m 755 /etc/systemd/system/ax-video-orchestrator.service.d

sudo install -o root -g root -m 644 deploy/systemd/environment.conf /etc/systemd/system/ax-video-orchestrator.service.d/environment.conf

sudo systemctl daemon-reload
sudo systemctl enable --now ax-video-orchestrator.service
~~~

확인:

~~~bash
systemctl is-active ax-video-orchestrator.service
systemctl is-enabled ax-video-orchestrator.service
curl -i http://127.0.0.1:8000/health
~~~

### 5. Caddy와 HTTPS

Caddy는 공식 Debian/Ubuntu stable 저장소의 패키지를 사용하십시오. 설치 절차는 Caddy 공식 문서에서 확인하고, 저장소 등록 후 sudo apt install caddy를 사용합니다.

deploy/Caddyfile.example을 복사하기 전에 도메인을 새 서버의 실제 도메인으로 변경합니다.

~~~bash
sudo install -o root -g root -m 644 deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
~~~

Caddy는 모든 경로를 FastAPI로 전달하므로 /videos/...를 별도로 직접 파일 서비스하지 않습니다.

### 6. DNS와 방화벽

1. 새 서버의 고정 공인 IP를 준비합니다.
2. DuckDNS 또는 DNS A 레코드를 새 IP로 변경합니다.
3. 클라우드 방화벽에서 TCP 80/443을 허용합니다.
4. 8000번 포트는 외부에 열지 않습니다.
5. DNS 전파 후 Caddy 인증서 발급과 HTTPS를 확인합니다.
6. 전환이 끝날 때까지 기존 서버를 유지하면 롤백이 쉽습니다.

AWS Lightsail 방화벽, DuckDNS 토큰과 SSH 키는 저장소에서 관리하지 않습니다.

## 검증

~~~bash
# 내부 health
curl -i http://127.0.0.1:8000/health

# 외부 HTTPS health
curl -i https://<운영 도메인>/health

# 인증 없는 Veo 생성 요청은 401이어야 하며 과금 호출을 시작하지 않음
curl -i -X POST https://<운영 도메인>/jobs -H 'Content-Type: application/json' --data '{"prompt":"authentication check","provider":"veo"}'

# 공개 영상 HEAD
curl -I https://<운영 도메인>/videos/job_<32자리-소문자-16진수>.mp4

# 공개 영상 Range
curl -i -H 'Range: bytes=0-1023' https://<운영 도메인>/videos/job_<32자리-소문자-16진수>.mp4 -o /dev/null
~~~

기대 결과:

- health: 200, {"status":"ok"}
- 무키 Veo 요청: 401
- 공개 영상 HEAD: 200, video/mp4, inline, Accept-Ranges: bytes
- 공개 영상 Range: 206과 Content-Range

POST /job-status는 JSON {"job_id":"job_..."}와 X-API-Key를 사용합니다. 실제 토큰은 URL이나 문서에 넣지 말고 SmartMaker의 안전한 설정에 보관하십시오.

## 로그와 장애 점검

~~~bash
systemctl status ax-video-orchestrator.service --no-pager
journalctl -u ax-video-orchestrator.service -n 100 --no-pager
systemctl status caddy --no-pager
journalctl -u caddy -n 100 --no-pager
ss -lntp
curl -i http://127.0.0.1:8000/health
~~~

기본 점검 순서:

1. FastAPI service가 active인지 확인
2. Uvicorn이 127.0.0.1:8000에만 바인딩됐는지 확인
3. 로컬 health 확인
4. Caddy 상태와 로그 확인
5. DNS가 현재 서버 IP를 가리키는지 확인
6. 외부 HTTPS 확인
7. 환경변수는 값을 출력하지 않고 정의 여부와 파일 권한만 확인

## 업데이트 배포 규칙

애플리케이션 소스만 변경한 경우:

~~~bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
sudo systemctl restart ax-video-orchestrator.service
~~~

이 경우 systemd daemon-reload와 Caddy reload는 일반적으로 필요하지 않습니다.

systemd unit 또는 drop-in 변경 시:

~~~bash
sudo systemctl daemon-reload
sudo systemctl restart ax-video-orchestrator.service
~~~

Caddyfile 변경 시:

~~~bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
~~~

Caddy 설정을 변경하지 않았다면 reload하지 않습니다.

## 이전과 백업

GitHub에 포함되는 것:

- 애플리케이션 소스와 테스트
- 공개 MP4 엔드포인트
- 비밀값 없는 배포 예시
- 변수명만 있는 .env.example

별도로 안전하게 이전해야 하는 것:

- /etc/ax-video-orchestrator.env의 실제 값
- outputs의 기존 MP4
- DuckDNS/DNS 설정과 토큰
- Lightsail 또는 클라우드 방화벽 규칙
- 필요한 운영 로그
- SSH 키와 서버 접근 설정

MP4는 서비스를 중지하지 않고 복사할 경우 생성 중인 .mp4.part를 피해야 합니다. 완성된 .mp4만 백업하거나 짧은 유지보수 시간에 일관된 스냅샷을 사용하십시오.

## 현재 PoC 제약과 운영 종속성

- 작업 상태는 프로세스 메모리에만 저장되며 재시작·이전 시 사라집니다.
- 진행 중인 백그라운드 작업은 재시작 시 복구되지 않습니다.
- MP4만 이전해도 과거 작업 상태 API는 복구되지 않습니다.
- DB, Redis, Celery, 영구 작업 큐가 없습니다.
- 기본 출력 경로는 소스 위치를 기준으로 계산한 <프로젝트 루트>/outputs입니다.
- Uvicorn 포트와 설치 절대경로는 systemd 예시에서 변경할 수 있습니다.
- 운영 도메인은 Caddy 예시에만 있으며 애플리케이션 코드에는 하드코딩되지 않습니다.
- API 키 누락 시 Veo 공급자는 안전하게 실패하며, 호출 인증키 누락 시 보호 API는 401을 반환합니다.
- 공유 토큰 하나를 사용하는 PoC 방식이며 사용자별 권한, 만료 URL, 속도 제한이 없습니다.
- 공개 영상 URL은 영구 공개 링크이므로 민감 영상에는 적합하지 않습니다.
