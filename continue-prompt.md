# Continue Prompt — vision-ocr-detect development handoff

세션 컨텍스트 리셋 후 작업 이어가기용 핸드오프. 다음 세션 첫 메시지로 붙여넣기.

---

## TL;DR

`vision-ocr-detect` (FastAPI + ollama/OpenRouter vision/OCR HTTP API) 프로젝트. interpark-ticket 프로젝트의 seat layout 추출 파이프라인이 클라이언트.

- **main HEAD**: `44d01d1` (현재 시점 — `git log --oneline -1`로 확인)
- **테스트**: 137/137 통과
- **서버**: `http://localhost:8000` 가동 중 (확인: `curl -sf http://127.0.0.1:8000/health`)
- **통신 패턴**: `collab-log.md` 단일 파일 양방향 (feature-bugs-followup-*.md 패턴 폐기)
- **현재 상태**: 모든 open threads CLOSED (§A §B §C §D). §C OpenRouter 통합은 코드 유지하되 production 운영은 보류.

---

## 프로젝트 개요

- **위치**: `/Users/dormael/my/clone/github.com/dormael/vision-ocr-detect/`
- **역할**: vision/OCR 모델 (로컬 ollama 또는 OpenRouter 게이트웨이) HTTP API로 노출. multipart 이미지 업로드, JSON 옵션, JSON 응답.
- **핵심 endpoint**: `POST /api/detect`
- **스택**: FastAPI 0.138+, httpx 0.28+, Pillow 12.2+, pydantic 2.13+, pydantic-settings 2.14+, jsonschema 4.26+, respx (dev), uvicorn[standard]. 패키지 매니저: uv.

## 통신 프로토콜

- **요청자**: interpark-ticket 프로젝트 (Playwright + TS CLI, seat layout 추출). 한국어 소통.
- **방식**: 단일 `collab-log.md` 파일. dev/requester/relay 모두 append-only entry 작성. `OPEN`/`WAITING-*`/`DECIDED` 상태 표시.
- **watch 패턴**: `tail -f collab-log.md` (요청자 측). dev는 user turn마다 파일 읽고 새 entry 확인.
- **구 entry 패턴** (deprecated, 보존만): `feature-bugs-followup-*.md` + `*-response.md`. 새 작업은 collab-log만 사용.

## 현재 상태 (collaborative)

### Closed threads
- **§A** (truncation detection): commit `05e72fe`. 422 detail에 text_length / last_nonempty_line / ends_with_unclosed_brace / suggestion 노출.
- **§B** (rule-based correction): 자체 측 `apply-corrections.ts --stage` + corrections.json. 26008115 recall 0.703 → 1.000, production mean 0.917.
- **§C** (OpenRouter 큰 모델 검토): qwen3-vl-32b/qwen2.5-vl-72b 추가 통합 보류 (recall 개선 없음). **핵심 발견**: 7b + json_schema 모드로 26000382 recall 1.000 가능 (dev §A fix chain 효과).
- **§D** (lenient default): 자체 측 CLI `--response-format json` 기본 적용.

### Open work (자체 측 결정 영역)
- **format-aware routing** (`extract-layout-api`): try-strict-then-lenient 자동 fallback. 자체 측 구현.
- **§B fuzzy match** (Levenshtein ≤ 2 rename): 26000382 misrecognition 해소 후보. 자체 측 결정.

## 주요 커밋 (최신순, 최신 20)

| 커밋 | 내용 |
|---|---|
| `44d01d1` | docs: config.example.json $comment fields |
| `85c7426` | docs: README OpenRouter + .env + bundled profiles |
| `58b4f84` | fix(detect): reject simple response_format=json for openrouter 422 |
| `16ae7cb` | feat(config): .env via pydantic-settings BaseSettings |
| `e92a60e` | feat(profiles): interpark-layout-32b / -72b |
| `344e1ec` | feat(providers): OpenRouter gateway |
| `659c5c2` | feat(logging): request params JSON in middleware log |
| `b2199cb` | fix(logging): uvicorn AccessFormatter + logging.json |
| `a53c48e` | feat(main): structured access log + request timing middleware |
| `05e72fe` | fix(detect): truncation signature in 422 detail |
| `8997d55` | fix(detect): null-tolerance retry for json_schema |
| `8f52fac` | docs: response to feature-bugs-followup-extra-4.md |
| `95537e8` | fix(profile): remove alphabetic example triggers |
| `0c4d953` | docs: README trade-off section + feature-review Bug 8 |
| `7143560` | fix(detect): max_tokens cap 8192 → 16384 |
| `0a2b03c` | OllamaProvider Option C (native / OpenAI-compat fallback) |
| `4cfd726` | #7 응답 메타 (tokens_in/out, cost_usd, seed_used, endpoint_used) |
| `d8c3cdd` | Bug 7 hotfix: lenient parser : +N / trailing comma / double comma |
| `e3f3079` | #2 완전형: OpenAI json_schema + jsonschema 서버측 검증 |
| `28eb067` | #13 models API |

## 핵심 기술 결정 (재현 필요)

1. **OllamaProvider 듀얼 호출** (`0a2b03c`):
   - native `/api/generate` 우선 (vision 호환성 ↑)
   - 404 또는 400+model-not-found → `/v1/chat/completions` OpenAI-compat fallback
   - 응답에 `endpoint_used: "native" | "openai" | null` 기록
   - native: `prompt_eval_count`/`eval_count`, OpenAI-compat: `usage.prompt_tokens`/`completion_tokens`

2. **Lenient JSON 파서** (`d8c3cdd` + `05e72fe`):
   - 순서: fence strip → `+N` 정규화 → trailing comma → `,,` → `,` → `json.loads`
   - 정규화는 `text` 필드 영향 X, `parsed`만 영향
   - `_drop_null_fields` retry: schema fail → null 제거 → 재검증 (json_schema only)

3. **OpenRouter provider** (`344e1ec`):
   - OpenAI-compat chat-completions
   - `OPENROUTER_API_KEY` env var 또는 config.json `api_key` (env 우선)
   - vision 분류는 name-based heuristic (`qwen.*vl` 등)
   - **`response_format="json"` 단순형 미지원** (400) → `{"type":"json_object"}` 또는 json_schema 객체만 (`58b4f84` 422 reject)

4. **Settings via pydantic-settings** (`16ae7cb`):
   - `BaseSettings` 상속, `env_file=".env"` 자동 로드
   - 우선순위: process env > .env > config.json > field default
   - nested 필드 (provider.api_key)는 자동 env 매핑 안 됨 — provider 클래스가 직접 env fallback 처리

5. **Structured logging** (`a53c48e` + `b2199cb` + `659c5c2`):
   - `logging.json` (source of truth) + `--log-config` CLI 플래그
   - access log: `client_addr - "request_line" status_code` (uvicorn AccessFormatter)
   - middleware log: `vision_ocr_detect.request` logger — `method/path/status/elapsed_ms [params=<json>]`
   - 422 detail에 truncation signature: `text_length=`, `ends_with_unclosed_brace=`, `last_nonempty_line=`, `suggestion=`

6. **PATCH-style PUT** (`7f496f3`):
   - `body.model_dump(exclude_unset=True)`로 명시 전달 필드만 머지
   - `description: null` → 명시적 clear, omission → 기존 값 유지

7. **max_tokens cap**: `le=16384` (Pydantic 검증). Ollama가 받아들이는 한계.

8. **fit=contain trade-off**: qwen2.5vl:7b white letterbox를 stage로 오인 가능. 정확한 stage_location 필요 시 `fit=fill` 권장. 작은 라벨 recall 우선이면 `fit=contain`.

## 디렉토리 구조

```
src/vision_ocr_detect/
├── api/
│   ├── detect.py          # POST /api/detect + 422 truncation + openrouter guard
│   ├── profiles.py        # /api/profiles CRUD
│   └── models.py          # GET /api/models, /api/providers/{name}/models
├── models/
│   ├── detect.py          # DetectOptions, DetectResponse, JsonSchemaResponseFormat
│   ├── image.py           # ImageOptions, ImagePreprocess, ResizeSpec, ResizeFit
│   └── profile.py         # Profile, ProfileOverride, tags/description
├── providers/
│   ├── base.py            # VisionProvider Protocol, ProviderResult, ModelInfo
│   ├── ollama.py          # native + OpenAI-compat 듀얼
│   ├── openrouter.py      # OpenAI-compat via OpenRouter
│   └── registry.py        # ProviderRegistry
├── services/
│   ├── image_processor.py # crop→preprocess→scale→resize→encode
│   └── profile_store.py   # JSON file store
├── config.py              # Settings (BaseSettings), ProviderConfig
└── main.py                # FastAPI app, lifespan, /health, middleware

tests/                       # 137 tests (test_detect_api, test_image_processor,
                             # test_profiles_api, test_models_api, test_config,
                             # test_provider_smoke, test_request_middleware,
                             # test_openrouter_provider)

config.example.json         # $comment_* 필드로 self-documenting
logging.json                # uvicorn access log + middleware log 설정

profiles.json               # 런타임 profile store (untracked, gitignore)
.env                        # OPENROUTER_API_KEY 등 (untracked, gitignore)
collab-log.md               # dev ↔ requester 통신 (untracked)

fixtures/
└── profiles/                # profile 템플릿 (committed)
    ├── interpark-layout.json     # qwen2.5vl:7b local
    ├── interpark-layout-32b.json # qwen3-vl-32b OpenRouter
    └── interpark-layout-72b.json # qwen2.5-vl-72b OpenRouter
```

## 서버 재시작

```bash
pkill -9 -f "uvicorn vision_ocr_detect" 2>/dev/null
OPENROUTER_API_KEY="$(grep OPENROUTER_API_KEY .env | cut -d= -f2)" \
  nohup uv run uvicorn vision_ocr_detect.main:app \
    --host 0.0.0.0 --port 8000 \
    --log-config logging.json \
    > /tmp/ocr-server-logs/server.log 2>&1 &
sleep 2 && curl -sf -o /dev/null -w "ready %{http_code}\n" http://127.0.0.1:8000/health
```

`OPENROUTER_API_KEY` prefix는 inline env (`.env` 직접 로드 미동작 시 우회).

## 첫 액션 (세션 시작 시)

1. **현재 상태 확인**:
   ```bash
   cd /Users/dormael/my/clone/github.com/dormael/vision-ocr-detect
   git log --oneline -5
   git status
   uv run pytest -q 2>&1 | tail -3
   curl -sf http://127.0.0.1:8000/health | python3 -m json.tool
   ```

2. **collab-log.md 새 entry 확인**:
   ```bash
   tail -50 collab-log.md
   ```

3. **새 entry 있으면**: 회신 entry 작성 (status: OPEN/WAITING/DECIDED 명시).

4. **서버 상태 불량 시**: 위 "서버 재시작" 명령.

## 자주 쓰는 명령어

```bash
# OpenRouter 모델 카탈로그 (11개 vision 자동 인식)
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# 422 detail 신규 format 확인 (truncation signature + suggestion)
curl -s -X POST http://127.0.0.1:8000/api/detect \
  -F profile=interpark-layout \
  -F image=@fixtures/layouts/26000634.gif \
  -F 'options={"response_format":"json","temperature":0.0,"seed":42}' \
  | python3 -m json.tool

# middleware log 실시간
tail -f /tmp/ocr-server-logs/server.log | grep -E "vision_ocr_detect.request|status="
```

## Hold 종료 트리거

요청자 측 회신 시:
1. `collab-log.md` 읽기 (or user turn 시작 시 자동)
2. 회신 entry 작성 (status 명시)
3. 합의 시 DECIDED + 별도 commit/PR 추출 가능

회신 트리거 (자체 측 가능 결정):
- format-aware routing 구현 결과
- §B fuzzy match 결정
- 26000382 accept 결정

---

**이 문서를 새 세션의 첫 메시지로 붙여넣으면 위 컨텍스트 그대로 복원됩니다.**