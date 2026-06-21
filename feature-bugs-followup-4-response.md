**제목**: [vision-ocr-detect] feature-bugs-followup-4.md 회신 — Option (c) hold 합의 확인

**본문**:

안녕하세요, `0a2b03c` 검증 + Option (c) 선택 확인. 자체 측 마이그레이션 진행 대기합니다.

## 1. 0a2b03c 검증 확인

라이브 재현 일치:

```json
{
  "endpoint_used": "native",
  "parsed": {...},
  "tokens_in": 1751,
  "tokens_out": 1952,
  "seed_used": 42,
  "elapsed_ms": 28812
}
```

자체 활용안 (endpoint_used 모니터링) 동의합니다. 모델 호환성 추적용으로 유용.

## 2. Option (c) hold — 합의 확인

자체 측 plan:

1. `extract-layout-api.ts` 신규 파일
2. 4 venue layout (26000382, 26000634, 26008115, 26007886) recall 측정
3. 결과 회신 후 다음 우선순위 합의

진행 중 합의 사항 발생 시 회신 주시면 즉시 대응하겠습니다.

## 3. 현재 main 상태 (자체 측 recall 측정 시 참고)

| 항목 | 상태 |
|---|---|
| main HEAD | `658b881` |
| 테스트 | 116/116 통과 |
| 서버 | `http://localhost:8000` 가동 중 (PID 79298, `0a2b03c` 반영) |
| OpenAPI docs | `http://localhost:8000/docs` |
| 신규 endpoints | `/api/models`, `/api/providers/{name}/models`, `?vision_only`, `/health.vision_models` |
| profile metadata | `tags`, `description`, `?tag=` 필터 |
| response_format | `"json"` (lenient) + `json_schema` (서버측 검증, 422 on fail) |
| 메타 필드 | `tokens_in/out, cost_usd, seed_used, endpoint_used` |

## 4. 자체 측 recall 측정 시 활용 가능 자료

`scripts/` 디렉토리 참고 자료:

- **`scripts/eval_bug8_compare.py`** — 단일 venue (26000634) cross-model 비교. qwen2.5vl:7b recall 0.458 측정 결과 있음. 자체 측 4 venue 측정 시 baseline 비교용.
- **`fixtures/Bug8-cross-model.md`** — Bug 8 진단 보고서 (5 모델 비교, 26000634 기준).

**자체 측 4 venue 측정 권장 사항**:

```bash
# 동일 baseline (recall 0.458 측정 시 사용한 옵션)
{
  "temperature": 0.0,
  "seed": 42,
  "image": {
    "format": "jpeg",
    "resize": {"width": 1200, "height": 1080, "fit": "contain", "background": "#ffffff"}
  },
  "response_format": {
    "type": "json_schema",
    "json_schema": {"name": "seat_layout", "schema": {...}}
  }
}
```

`response_format: json_schema` 권장 — 모델 enum 위반 / 필드 누락 시 422로 즉시 차단, apply-corrections 부담 경감.

## 5. 측정 결과 회신 시 함께 받을 정보

자체 측 효과 분석 위해 다음 데이터 회신 부탁드립니다:

| 항목 | 측정값 |
|---|---|
| venue별 recall (26000382, 26000634, 26008115, 26007886) | |
| endpoint_used 분포 (native vs openai vs null) | |
| 422 발생 빈도 (json_schema 위반) | |
| api 경유 vs native 직접 회귀 비교 | |
| elapsed_ms (per venue) | |

## 6. 자체 측 대기 중

서버는 가동 상태 유지. 회신 받으면:
- recall 회귀 시: prompt 튜닝 / json_schema 추가 제약 / 옵션 합의
- recall 개선 시: 다음 feature 우선순위 재논의
- 부수 이슈 발생 시: hotfix 진행

기다리겠습니다.

감사합니다.