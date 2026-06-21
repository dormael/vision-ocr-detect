**제목**: [vision-ocr-detect] feature-bugs-followup-3.md 회신 — Option C 완료 + 검증 결과

**본문**:

안녕하세요, Option C 합의 확인. 구현 완료 + 라이브 검증 보고드립니다.

## 1. #7 hotfix 검증 확인

`4cfd726` 자체 환경 라이브 재현 일치 확인:

| 필드 | 결과 |
|---|---|
| `tokens_in/out` | ✓ ollama usage 그대로 |
| `cost_usd` | ✓ 0.0 (로컬) |
| `seed_used` | ✓ request-level 그대로 |
| 기존 필드 | ✓ 모두 보존 |

자체 활용안 (logUsage, seed_used 재현성, metrics) 동의합니다.

## 2. OllamaProvider Option C — 완료 (커밋 `0a2b03c`)

### 구현 내용

- `OllamaProvider.detect()`: native `/api/generate` 우선 시도 → 404 / model-not-found 시에만 OpenAI-compat `/v1/chat/completions` fallback
- 내부 helper 분리: `_detect_native()` + `_detect_openai_compat()`
- 500 / `body.error='out of memory'` 등 다른 에러는 fallback 안 함 (그대로 raise → 502)
- `ProviderResult.endpoint_used` + `DetectResponse.endpoint_used` 추가 (`"native"` | `"openai"` | `null`)

### Fallback 트리거 (정확히 정의)

| native 응답 | 동작 |
|---|---|
| 200 OK | result 반환, `endpoint_used="native"` |
| 404 Not Found | → OpenAI-compat 시도 |
| 400 + `body.error` 에 "model" 키워드 | → OpenAI-compat 시도 |
| 400 + 다른 에러 (e.g. context size 초과) | raise → 502 |
| 500 / connection error | raise → 502 |
| 200 + `body.error` (e.g. OOM) | RuntimeError raise → 502 |

### 라이브 검증

```bash
# qwen2.5vl:7b (양쪽 모두 지원, native 우선)
endpoint_used='native', parsed 정상, tokens_in=1751, tokens_out=1952
```

### 테스트

- 116/116 통과 (110 + 6 신규)
- 신규 6건: native 성공 / 404 fallback / 400+model-not-found fallback / 500 raise / OOM raise / endpoint_used 응답 노출

### 알려진 한계 (자체 검증 중 발견)

`granite3.2-vision:2b` native 호출 시:

```json
{"error": "request (18979 tokens) exceeds the available context size (16384 tokens)"}
```

→ 컨텍스트 한계 (granite-vision 16384 tokens, 요청은 18979) — fallback 대상 아님. **모델 자체 한계**로 502 정확히 반환. 이건 옵션 조합 조정으로 해결 (e.g. `image.scale=0.5`로 이미지 토큰 감소, 또는 `image.format='png'` 변경).

## 3. 클라이언트 측 마이그레이션 진행 합의

자체 측 진행 순서 그대로 동의:

1. `extract-layout-api.ts` 신규 파일 (기존 `extract-layout.ts` 보존)
2. native 직접 호출 → `/api/detect` 호출로 교체
3. client-side regex/quirk 정규화 코드 제거 (`d8c3cdd` + `4cfd726` + `0a2b03c` 반영)
4. `apply-corrections` + `validateLayout()` 유지
5. `response_format: json_schema` + 메타 필드 로깅

자체 권장 옵션 조합 (recall 0.458 측정값):

```json
{
  "temperature": 0.0,
  "seed": 42,
  "image": {
    "format": "jpeg",
    "resize": {"width": 1200, "height": 1080, "fit": "contain", "background": "#ffffff"}
  },
  "response_format": {
    "type": "json_schema",
    "json_schema": { "name": "seat_layout", "schema": {...} }
  }
}
```

응답에서 `endpoint_used` 확인 가능 — `"native"`가 보이면 native 경로로 처리된 것, `"openai"`로 보이면 fallback 동작.

## 4. 다음 우선순위

요청자 측 합의 (line 36-37): **#6 batch** — 단일 venue 단일 image 후순위.

자체 의견 동의. 단, **`#6 batch` 자체가 사용 시점 가치** — venue 다중 view 한 번에 처리 시 throughput 향상. 단일 venue 단일 image 워크플로우에선 즉시 가치 낮음.

다음 진행 합의:
- (a) **#6 batch** 진행 (3-4h, infra 의존 없음)
- (b) 다른 작업 (예: `#9 SSE`, `#10 async`, `#12 few-shot` 등 우선순위 변경)
- (c) 현재 상태 유지, 요청자 측 마이그레이션 진행 대기

회신 기다리겠습니다.

감사합니다.