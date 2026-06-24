# Continue Prompt — vision-ocr-detect (handoff, stable)

`vision-ocr-detect` 협업 arc 종료 상태. **운영 stable**, mean recall **1.000** (3 venue 모두 perfect).

---

## TL;DR

- **상태**: production stable. 자체 측 운영 1.000 recall. dev 측 추가 작업 없음.
- **main HEAD**: `e1eb9f7` (최신 — `git log --oneline -1`로 확인)
- **테스트**: 138/138 (ollama smoke 제외 137개 단위/통합 + 1개 smoke)
- **협업 arc**: closed. §A §B §C §D 모두 결정. `collab-log.md`에 역사 보존.
- **새 작업**: 없음. 유지보수만 필요.

---

## 운영 상태 (production stable)

```
strict json_schema → on 422 / truncation → lenient → §B patch
```

자체 측 운영 baseline:

| 시점 | 운영 모드 | mean |
|---|---|---|
| 2026-06-22 | json_schema strict | 0.518 |
| 2026-06-23 | lenient | 0.838 |
| 2026-06-24 | lenient + §B | 0.917 |
| **2026-06-25** | **strict + fallback + §B** | **1.000** |

---

## 프로젝트 위치

- **dev repo**: `/Users/dormael/my/clone/github.com/dormael/vision-ocr-detect/`
- **client repo** (interpark-ticket): `/Users/dormael/my/clone/github.com/dormael/interpark-ticket/`
- **서버**: `http://localhost:8000` (확인: `curl -sf http://127.0.0.1:8000/health`)
- **서버 로그**: `/tmp/ocr-server-logs/server.log`

---

## 디렉토리 (핵심 파일)

```
src/vision_ocr_detect/
├── api/
│   ├── detect.py          # POST /api/detect, 422 truncation detail, openrouter guard
│   ├── profiles.py        # /api/profiles CRUD
│   └── models.py          # GET /api/models, /api/providers/{name}/models
├── models/
│   ├── detect.py          # DetectOptions, DetectResponse, JsonSchemaResponseFormat
│   ├── image.py           # ImageOptions, ImagePreprocess, ResizeSpec
│   └── profile.py         # Profile, ProfileOverride, tags/description
├── providers/
│   ├── base.py            # VisionProvider Protocol
│   ├── ollama.py          # native /api/generate + OpenAI-compat fallback
│   ├── openrouter.py      # OpenAI-compat gateway (운영 미사용, 코드 유지)
│   └── registry.py
├── services/
│   ├── image_processor.py # crop → preprocess → scale → resize → encode
│   └── profile_store.py
├── config.py              # Settings (BaseSettings, .env 자동 로드)
└── main.py                # FastAPI app, lifespan, middleware, load_log_config()

tests/                       # 138 tests
config.example.json         # $comment_* self-documenting
logging.json                # uvicorn + middleware log 설정
profiles.json               # 런타임 store
.env                        # OPENROUTER_API_KEY (운영 미사용이지만 설정됨)
collab-log.md               # 협업 역사 보존 (git 추적)

fixtures/profiles/
├── interpark-layout.json     # qwen2.5vl:7b local
├── interpark-layout-32b.json # OpenRouter 보류 결정 후 미사용
└── interpark-layout-72b.json # OpenRouter 보류 결정 후 미사용
```

---

## 핵심 기술 결정 (유지보수 시 참조)

| 결정 | commit | 핵심 |
|---|---|---|
| Ollama 듀얼 호출 | `0a2b03c` | native 우선, 404 시 OpenAI-compat fallback |
| Lenient parser | `d8c3cdd` | fence strip → +N 정규화 → trailing/double comma |
| Null-tolerance retry | `8997d55` | json_schema mode: 1차 fail → null drop → 2차 검증. **운영 1.000의 hidden enabler** |
| Truncation signature | `05e72fe` | 422 detail에 text_length / last_nonempty_line / ends_with_unclosed_brace / suggestion |
| Response meta | `4cfd726` | tokens_in/out, cost_usd, seed_used, endpoint_used |
| Pydantic-settings .env | `16ae7cb` | `BaseSettings` 상속, .env 자동 로드 |
| Structured logging | `a53c48e` + `b2199cb` + `659c5c2` | access log + middleware log + params JSON |
| Logging 단일 출처 | `43c7eae` | `load_log_config()` reads logging.json |
| OpenRouter tolerant | `92824fb` | constructor warn (not raise), detect 시점 fail |
| OpenRouter guard | `58b4f84` | `response_format="json"` 단순형 → openrouter 422 (대신 400 cascade) |
| PATCH-style PUT | `7f496f3` | `model_dump(exclude_unset=True)` |

---

## 자주 쓰는 명령어

```bash
# 서버 상태
curl -sf http://127.0.0.1:8000/health | python3 -m json.tool

# 서버 재시작 (OPENROUTER_API_KEY 우회 — .env cwd 미해결 시)
pkill -9 -f "uvicorn vision_ocr_detect" 2>/dev/null
OPENROUTER_API_KEY="$(grep OPENROUTER_API_KEY .env | cut -d= -f2)" \
  nohup uv run uvicorn vision_ocr_detect.main:app \
    --host 0.0.0.0 --port 8000 \
    --log-config logging.json \
    > /tmp/ocr-server-logs/server.log 2>&1 &
sleep 2 && curl -sf -o /dev/null -w "ready %{http_code}\n" http://127.0.0.1:8000/health

# Tests
uv run pytest --ignore=tests/test_provider_smoke.py  # 137 unit/integ
uv run pytest tests/test_provider_smoke.py             # real ollama (skips if unreachable)

# 422 detail 신규 format (truncation signature) 확인
curl -s -X POST http://127.0.0.1:8000/api/detect \
  -F profile=interpark-layout \
  -F image=@fixtures/layouts/26000634.gif \
  -F 'options={"response_format":"json","temperature":0.0,"seed":42}' \
  | python3 -m json.tool

# middleware log 실시간 (X-Process-Time + params=<json>)
tail -f /tmp/ocr-server-logs/server.log | grep -E "vision_ocr_detect.request"

# 협업 역사 (git 추적, 1056 lines)
cat collab-log.md | less
```

---

## 유지보수 트리거

- 자체 측 새 venue 추가 (예: 26007886 NOL)
- 자체 측 recall 회귀 (현재 1.000에서 하락)
- 새 provider 요청 (Anthropic, Groq 등) — `add a new provider type` 패턴 (README 참조)
- cost_per_1k TODO 해결 (현재 0.0 placeholder, 실제 가격 도입 시 per-model 함수 필요)
- Ollama 버전 업그레이드로 native/OpenAI-compat 동작 변화 시
- uvicorn 버전 업그레이드 시 `AccessFormatter` 변경 가능성

---

## 협업 arc (history)

- **전체 arc**: `6704755` (initial) → `e1eb9f7` (final confirm)
- **주요 fix chain**: `0a2b03c`, `d8c3cdd`, `e3f3079`, `0c4d953`, `8997d55`, `95537e8`, `05e72fe`, `b2199cb`, `659c5c2`
- **OpenRouter (보류 결정)**: `344e1ec`, `e92a60e`, `16ae7cb`, `58b4f84`, `92824fb`
- **협업 패턴 전환 (legacy → 단일 파일)**: 2026-06-23. `feature-bugs-followup-*.md` 패턴 폐기, `collab-log.md` 단일 채택
- **상세**: `collab-log.md` (1056 lines, 모든 thread 결정 보존)

---

## Hold 종료 트리거

없음. **협업 arc 종료 상태**. 새 작업 요청 시에만 활성화.

---

**이 문서를 새 세션의 첫 메시지로 붙여넣으면 위 컨텍스트 그대로 복원됩니다.**