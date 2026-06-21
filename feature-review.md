# Feature Request Review

**대상**: `feature-request.md` (interpark-ticket 프로젝트 요청)
**검토일**: 2026-06-21
**갱신일**: 2026-06-21 (P0-Sprint1, P1-Sprint2 완료 반영)
**현재 상태**: main @ `8bf79fc`, **69/69 tests pass**

요청 12건을 effort/영향/리스크 기준으로 분류. 우선순위는 제안이며 사용자 확인 필요.

---

## 완료 현황

| Sprint | 항목 | 커밋 | 테스트 |
|---|---|---|---|
| **Sprint 1** | #1 GIF 입력 지원 | `9e4f226` | `test_animated_gif_uses_first_frame` |
| Sprint 1 | #2 response_format (단순형) | `b1f65cb`, `8345a1b` | `test_response_format_*` (4개) |
| Sprint 1 | #3 profile_override | `b1f65cb`, `8345a1b` | `test_profile_override_*` (5개) |
| **Sprint 2** | #4 image.preprocess | `ce8b86a`, `e5846d1` | `test_preprocess_*` (8개) |
| Sprint 2 | #5 image.fit | `ce8b86a`, `e5846d1` | `test_fit_*` (6개) |
| hotfix | Bug 1-5 (preprocess 500) | `489fdf7` | `test_palette_gif_with_preprocess_does_not_raise` |
| hotfix | Bug 6 (top-level seed) | `09c663d` | `test_top_level_seed_*` (3개) |
| hotfix | Bug 7 (markdown fence) | `8bf79fc` | `test_response_format_strips_*` (2개) |

남은 작업은 **다음 섹션** 참조.

---

## 다음 후보 (우선순위 재합의용)

| 순위 | 항목 | 출처 | effort | 비고 |
|---|---|---|---|---|
| 🟢 **P2-즉시** | **#8 profile metadata** (tags, description + `?tag=` 필터) | 요청자 | 1-2h | pydantic default로 기존 profile 자동 호환, 마이그레이션 무필요 |
| 🟢 **P2-즉시** | **#13 모델 조회 API** (vision-filtered, 미요청이지만 Bug 8 진단 중 필요성 확인) | 자체 | 2-3h | ollama `/api/tags`의 `capabilities` 필드 + 이름 휴리스틱 fallback |
| 🟡 P1-단기 | #2 response_format **완전형** (OpenAI `json_schema` 객체 + 서버측 schema 검증) | 요청자 | 1-2일 | `jsonschema` lib 추가, typed schema |
| 🟢 P2-중기 | #6 batch (multi-image) | 요청자 | 3-4h | infra 의존 없음. 부분 실패 처리 + 동시성 정책 합의 필요 |
| 🟢 P2-중기 | #7 응답 메타 (tokens_in/out, cost_usd, seed_used) | 요청자 | 3-4h | protocol 변경 필요 (모든 provider 영향) |
| ⚪ P3-보류 | #9 SSE 스트리밍 | 요청자 | 1일 | client UX 합의 + endpoint 분기 결정 |
| ⚪ P3-보류 | #10 async mode + #11 cancel | 요청자 | 1.5-2일 | in-memory job dict + TTL, multi-replica 시 Redis 도입 |
| ⚪ P3-보류 | #12 few-shot attachments | 요청자 | 1-2일 | 저장소 결정 (base64 vs filesystem vs S3) |

**권장 다음 스프린트** (Sprint 3):
- `#8 profile metadata` + `#13 모델 조회 API` (총 3-5h, P2 항목 중 가장 작은 effort)

---

## P0 — Sprint 1 완료 (참고용 기록)

### #1 GIF 입력 지원 ✅ 완료
**커밋**: `9e4f226` — `feat(image): handle animated GIF by extracting first frame`
**테스트**: `test_animated_gif_uses_first_frame`

### #2 `response_format` (단순형) ✅ 완료
**커밋**: `b1f65cb`, `8345a1b`
- `DetectOptions.response_format: Literal["json"] | None`
- `parsed: dict | None` 응답 필드 추가 (실패 시 null, text 보존)
- ollama `format` 전달
- **잔여 갭**: OpenAI `json_schema` 객체 + 서버측 검증 (P1-단기로 분류)

### #3 `profile_override` ✅ 완료
**커밋**: `b1f65cb`, `8345a1b`
- 5 필드 (provider/model/prompt/temperature/seed) 머지
- provider 변경 시 cross-provider 검증 (400)
- temperature 우선순위: request > override > None

---

## P1 — Sprint 2 완료 (참고용 기록)

### #4 `image.preprocess` ✅ 완료 + Bug 1-5 hotfix
- `ImagePreprocess` 모델 + `_apply_preprocess` 파이프라인
- `sharpen` (UnsharpMask), `contrast`, `brightness`, `binarize`
- **hotfix `489fdf7`**: GIF `mode="P"` → `"RGB"` 변환 (ImageEnhance 거부 회피)
- 테스트 8개 (sprint2) + 1개 (hotfix)

### #5 `image.fit` ✅ 완료
- `ResizeFit` = `fill` | `contain` | `cover`
- hex `background` (letterbox 색)
- `_resize_with_fit` 함수
- 테스트 6개

---

## Bug Report (`feature-bugs.md`) 처리 현황

| Bug | 상태 | 비고 |
|---|---|---|
| 1-5 (preprocess 500) | ✅ `489fdf7` | GIF 팔레트 모드 → RGB 변환 |
| 6 (top-level seed) | ✅ `09c663d` | `DetectOptions.seed` 필드 추가 |
| 7 (markdown fence) | ✅ `8bf79fc` | `_strip_markdown_fence` 헬퍼 |
| 8 (품질 회귀) | 🔵 진단 완료 | **VLM 한계** (qwen2.5vl:7b + prompt). API는 정상, 마이그레이션 보류 해제 가능. 추가 모델 비교 평가 후 권장안 정리 (`fixtures/`, `scripts/eval_bug8.py`) |

---

## 아키텍처 영향 매트릭스 (현 상태)

| 요청 | protocol 변경 | API 변경 | store 변경 | 신규 의존성 | 상태 |
|---|---|---|---|---|---|
| #1 GIF | ✗ | OpenAPI only | ✗ | ✗ | ✅ |
| #2 json_schema (단순형) | ✗ (ollama만) | 옵션 + 응답 | ✗ | ✗ | ✅ |
| #2 json_schema (완전형) | ✗ | 옵션 | ✗ | jsonschema | P1-단기 |
| #3 profile_override | ✗ | 옵션 | ✗ | ✗ | ✅ |
| #4 preprocess | ✗ | 옵션 | ✗ | ✗ | ✅ |
| #5 fit | ✗ | 옵션 | ✗ | ✗ | ✅ |
| #6 batch | ✗ | endpoint | ✗ | ✗ | P2-중기 |
| #7 response meta | **✓** | 응답 | ✗ | ✗ | P2-중기 |
| #8 profile meta | ✗ | endpoint | schema 확장 | ✗ | **P2-즉시** |
| #9 SSE | ✗ (provider) | endpoint | ✗ | ✗ | P3-보류 |
| #10 async | ✗ | endpoint + job store | **✓** | redis? | P3-보류 |
| #11 cancel | ✗ | endpoint | job store 의존 | ✗ | P3-보류 |
| #12 few-shot | **✓** (prompt 조립) | ✗ | **✓** (이미지) | 스토리지 결정 | P3-보류 |
| #13 models API | **✓** (list_models) | endpoint | ✗ | ✗ | **P2-즉시** |

---

## 다음 단계

`Sprint 3`:
1. **`#8 profile metadata`** (P2-즉시, 1-2h) — 작은 effort, 즉시 가치
2. **`#13 모델 조회 API`** (P2-즉시, 2-3h) — Bug 8 진단 / 향후 multi-model 운영 기반

진행 합의 시 plan mode로 들어가서 구현 계획 세우겠음.
