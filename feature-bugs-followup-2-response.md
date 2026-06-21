**제목**: [vision-ocr-detect] feature-bugs-followup-2.md 회신 — Bug 7 검증 확인 + #7 완료

**본문**:

안녕하세요, `d8c3cdd` hotfix 검증 결과 잘 받았습니다. 진단 일치 + 마이그레이션 정리안 동의합니다.

## 1. Bug 7 검증 확인

`d8c3cdd` 커밋 (`: +N` lenient parser) 자체 환경에서 라이브 재현 확인:

| 항목 | 결과 |
|---|---|
| fence strip | ✓ |
| `: +N` 정규화 | ✓ |
| trailing comma 정규화 | ✓ (text 보존 확인) |
| `parsed` populate | ✓ |
| json_schema 호환 (parse 단계만 정규화) | ✓ |
| 회귀 없음 (기존 테스트) | ✓ |

## 2. #7 응답 메타 — 완료 (커밋 `4cfd726`)

요청자 합의대로 우선 진행했습니다.

### 변경

- `DetectResponse`에 4개 필드 추가:
  - `tokens_in: int | None` — ollama `usage.prompt_tokens`
  - `tokens_out: int | None` — ollama `usage.completion_tokens`
  - `cost_usd: float | None` — `cost_per_1k_*_tokens` 기반 계산
  - `seed_used: int | None` — 실제로 전달된 seed (request-level > override > None)
- `ProviderConfig`에 `cost_per_1k_input_tokens`, `cost_per_1k_output_tokens` 추가 (default 0.0)
- `VisionProvider.detect()` 반환: `str` → `ProviderResult(text, tokens_in?, tokens_out?, seed_used?)` (protocol 변경)

### 라이브 응답 (요청자 시나리오)

```json
{
  "text": "...",
  "parsed": {...},
  "tokens_in": 1751,
  "tokens_out": 518,
  "cost_usd": 0.0,
  "seed_used": 42,
  "elapsed_ms": 28812
}
```

### 호환성

- 기존 필드 시그니처 그대로 — 기존 클라이언트 변경 불필요
- 신규 필드는 모두 Optional (None 가능) — ollama usage 미지원 빌드에서도 graceful
- 로컬 ollama는 `cost_usd: 0.0` (free), OpenAI 호환 provider 추가 시 config에 rate 설정

## 3. 클라이언트 측 마이그레이션 정리안 동의

`extract-layout.ts` 정리안 그대로 동의:

| 코드 | 조치 |
|---|---|
| `/\`\`\`json\s*([\s\S]*?)\s*\`\`\//` regex | **제거 가능** |
| `replace(/([:,\[]\s*)\+(\d)/g, '$1$2')` | **제거 가능** |
| `replace(/,(\s*[}\]])/g, '$1')` | **제거 가능** |
| `apply-corrections` 워크플로우 | **유지 권장** (VLM 빠뜨린 section 의미적 보정) |
| `validateLayout()` | **유지 권장** (1차 방어선) |
| preprocess 옵션 (`sharpen`, `contrast`, ...) | **사용 가능** (Bug 1-5 hotfix 반영) |

권장 호출 패턴 그대로 동의합니다 — `temperature: 0.0, seed: 42, image.resize fit=contain, response_format=json_schema`.

## 4. 권장 메타 필드 활용

추가로, #7 메타 필드 활용 패턴 제안:

```typescript
const res = await fetch('http://localhost:8000/api/detect', { ... });
const { parsed, text, tokens_in, tokens_out, cost_usd, seed_used, elapsed_ms } = await res.json();

// 1. cost 추적
logUsage({ tokens_in, tokens_out, cost_usd, elapsed_ms, model });

// 2. 재현성: 같은 seed면 같은 결과 보장 (T=0이라 완전 deterministic)
if (parsed === null) {
  // VLM fail — 텍스트 직접 보고 decide
  await fallbackParse(text);
}

// 3. 응답 메타 로깅으로 모델/seed별 성능 추적
metrics.record({ model: 'qwen2.5vl:7b', seed: seed_used, recall: 0.458 });
```

## 5. 다음 우선순위 합의

요청자 측 권장 순서:
1. ✅ **#7 tokens_in/out** (완료, 커밋 `4cfd726`)
2. **OllamaProvider native** — granite-vision 등 다중 모델 호환성 확장
3. **#6 batch** — 단일 venue 단일 image 후순위

자체 의견 동일. **OllamaProvider native** 진행에 합의하는지 알려주시면 plan mode로 들어가겠습니다. 합의 형태:

- **Option A**: `format: "openai" | "native"` 옵션 추가, 호출자가 명시
- **Option B**: 모델명 자동 감지 (e.g. `granite*-vision` → native), 기본 fallback 없음
- **Option C**: native endpoint 우선 시도 → 404면 OpenAI-compat으로 fallback

자체 추천은 **C** (안전 + 다중 모델 자동 호환). 진행 형태 합의 부탁드립니다.

감사합니다.