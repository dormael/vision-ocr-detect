**제목**: [vision-ocr-detect] feature-bugs.md 검토 결과 회신 — hotfix 완료 + Bug 8 진단 결과

**본문**:

안녕하세요, vision-ocr-detect 검토 피드백 잘 받았습니다. 회신이 늦어 죄송합니다. 다음 순서로 보고드립니다.

## 1. 즉시 수정 버그 hotfix — 완료 (커밋 머지됨)

| Bug | 커밋 | 수정 |
|---|---|---|
| 1-5 (preprocess 500) | `489fdf7` | GIF `mode="P"` → `_decode` 끝에서 RGB 변환 (ImageEnhance/ImageFilter 거부 회피) |
| 6 (top-level seed) | `09c663d` | `DetectOptions.seed` 필드 추가 + wiring (request > override > None 우선순위) |
| 7 (parsed null with fence) | `8bf79fc` | lenient parse에 markdown fence strip 정규식 추가 (text 자체는 보존) |

추가로 **#2 완전형**(요청서 line 53-90, OpenAI 스타일 `response_format: {type: "json_schema", ...}`)도 이번 회차에 함께 진행했습니다. 커밋 `e3f3079`:

- `json_schema` 모드: 서버측 `jsonschema` 라이브러리로 검증
- 파싱 실패 + 스키마 불일치 → **422** (요청서 line 90 "VLM이 잘못된 JSON 생성 시 422로 빠르게 실패" 그대로 구현)
- `response_format: "json"` 단순형은 기존대로 lenient (parsed=null 시 text 보존)

테스트 96/96 통과, API 동작 확인 완료.

## 2. Bug 8 (품질 회귀) — 진단 완료

전달받은 fixtures로 자체 환경에서 재현·평가 완료했습니다 (`scripts/eval_bug8_compare.py`, `fixtures/Bug8-cross-model.md` 참조).

### Cross-model 비교 결과 (fit=contain 1200x1080 + jpeg 베이스라인)

| Model | parsed | recall | precision | 환각 | floor_acc | stage_pred | 비고 |
|---|---|---|---|---|---|---|---|
| **qwen2.5vl:7b** | ✓ | **0.458** | 0.846 | 0.154 | **0.909** | CENTER | 11 TP / 2 FP / 13 FN |
| deepseek-ocr:3b | ✗ | 0.000 | — | — | — | — | 산문만 출력, JSON 미생성 |
| glm-ocr:latest | ✗ | 0.000 | — | — | — | — | 필드명 hallucination (`d距离_tier` 등) |
| granite3.2-vision:2b | ✗ | — | — | — | — | — | ollama OpenAI-compat 미지원 (네이티브 `/api/generate`는 동작) |
| minicpm-v:8b | ✗ | — | — | — | — | — | "no image" 응답 (이미지 미수신) |

### 결론

1. **qwen2.5vl:7b가 사용 가능한 5개 모델 중 최고**입니다. 다른 모델은 대체로 사용 불가 (hallucination, 산문 출력, 또는 OpenAI-compat 호환성 부족).
2. **Bug 8은 모델 선택 문제가 아닙니다** — 요청자분이 이미 가장 강한 모델을 선택하셨고, recall 0.458은 해당 모델 자체의 layout-extraction 한계입니다.
3. **마이그레이션 보류 권고 해제 가능**: API 자체는 정상 동작합니다. Hotfix 후 preprocess 옵션(sharp, contrast, binarize) 모두 사용 가능하고, json_schema 모드로 출력을 typed schema로 강제할 수 있습니다.

### 권장 옵션 조합 (자체 평가 기준)

```bash
curl -X POST localhost:8000/api/detect \
  -F 'profile=interpark-layout' \
  -F 'image=@layouts/26000634.gif' \
  -F 'options={"temperature":0.0,"seed":42,"response_format":{"type":"json_schema","json_schema":{"name":"seat_layout","schema":{...}}},"image":{"format":"jpeg","resize":{"width":1200,"height":1080,"fit":"contain","background":"#ffffff"}}}'
```

- `fit=contain`: 600x540 → 1200x1080 letterbox가 stage_location 인식 개선 (자체 평가에서 stage=TOP 정확)
- `response_format=json_schema`: 모델 출력 오타 시 422로 즉시 실패 → 클라이언트 측 보정 코드 제거 가능
- `seed`: 재현성 확보 (request-level, top-level 옵션)

### 진단 중 발견한 production follow-up (참고용)

| 항목 | 내용 |
|---|---|
| OpenAI-compat 호환성 | 일부 비전 모델(granite, minicpm)이 `/v1/chat/completions` 미지원. 네이티브 `/api/generate`만 동작. 현재는 qwen2.5vl 사용에 문제 없음. 향후 다중 모델 운영 시 native 옵션 추가 가치 있음. |
| Lenient 파서 강화 | 서버의 lenient 파서는 fence strip만 처리. `+`/trailing comma는 production에서도 보정하지 않음 (scoring 전용으로 분리). OCR 워크플로우에서 parsed=null이 잦으면 strict 옵션 도입 고려. |

## 3. 추가 작업 정리

진행한 작업 (요청 외):

| 항목 | 커밋 | 비고 |
|---|---|---|
| feature-review.md 갱신 | `b75f019` | stale → main `8bf79fc` 기준 |
| #8 profile metadata (tags, description, ?tag=) | `7f496f3` | pydantic default로 기존 profile 자동 호환 |
| #13 models API (vision-filtered) | `28eb067` | ollama capabilities + 휴리스틱 fallback |

## 4. 다음 우선순위 합의 요청

다음 후보 중 어느 항목 우선 진행할지 알려주시면 그쪽으로 plan 모드 들어가겠습니다:

- **#7 응답 메타** (tokens_in/out, cost_usd, seed_used) — protocol 변경 (3-4h)
- **#6 batch** (multi-image, 부분 실패 정책 합의 필요) — 3-4h
- **OllamaProvider native 옵션** — granite-vision 등 호환성 확장 (2-3h, 자체 결정)
- **기타 우선순위 항목** — 명시 부탁드립니다

검토 후 회신 부탁드립니다.

감사합니다.