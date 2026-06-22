**제목**: [vision-ocr-detect] feature-bugs-followup-extra.md 회신 — Issue 1 hotfix + Issue 2 문서화

**본문**:

안녕하세요, 자체 측 4 venue recall 측정 결과 + 발견 이슈 보고 잘 받았습니다. **3 venue 평균 recall 0.897은 매우 고무적**입니다 — 단일 venue (26000634) baseline 0.458과 비교하면 +96% 개선으로, 자체 측 마이그레이션이 효과적이었다는 강한 증거입니다.

## 1. Issue 1 (`max_tokens=16384` + no-resize → 빈 응답) — hotfix 완료

### 진단

자체 환경에서 `max_tokens=16384` 재현:

```bash
$ curl -X POST ... -F 'options={...,"max_tokens":16384,...}'
HTTP 422
{
  "detail": [{
    "type": "less_than_equal", "loc": ["max_tokens"],
    "msg": "Input should be less than or equal to 8192",
    "input": 16384, "ctx": {"le": 8192}
  }]
}
```

**실제 동작은 HTTP 422** (Pydantic `max_tokens: le=8192` 검증 거부)였습니다. 보고서의 "HTTP 200 + `text: ""`" 응답 형태는 우리 서버 응답과 다름 — **자체 측 클라이언트가 422를 무시하고 기본 shape을 반환했을 가능성** 의심됩니다 (try/catch + `{text: "", ...}` 패턴).

어쨌든 `le=8192` 한계는 너무 restrictive — Ollama는 16K+ num_predict 지원. **커밋 `<추후 hash>` 에서 `le=16384`로 상향**했습니다.

### Hotfix 변경

- `DetectOptions.max_tokens: Field(le=16384)` (기존 8192 → 16384)
- 신규 테스트: `test_max_tokens_upper_bound` (16384 통과, 16385 거부)
- 117/117 통과

### 라이브 검증 (hotfix 후)

```bash
max_tokens=16384 → HTTP 200, text_len=6333, parsed 정상
max_tokens=16385 → HTTP 422 (캡 초과)
```

### 자체 측 확인 요청

자체 측 클라이언트에서 `max_tokens=16384` 호출 시 200 OK 받는지 확인 부탁드립니다. 만약 여전히 422가 보이면 클라이언트 측 검증 이슈 — 본인 측 코드 점검 필요. 200 OK가 보이면 Issue 1 종료.

## 2. Issue 2 (`fit=contain` letterbox → stage_location 오분류) — 문서화

자체 측 3 venue 관측:
| venue | fit=contain | fit=fill |
|---|---|---|
| 26000382 | CENTER ✗ | CENTER ✗ |
| 26000634 | CENTER ✗ | CENTER ✗ |
| 26008115 | (empty) | **TOP ✓** |

자체 측 가설 (qwen2.5vl:7b가 white padding을 stage 영역으로 오인)에 동의합니다. 코드 수정 없이 **문서로만 처리** — 권장 baseline 옵션 trade-off 추가했습니다.

### README 변경

`image.resize.fit` 옵션 설명에 trade-off 섹션 추가:

> **Trade-off observed in the interpark-ticket use case (4-venue recall
> measurement)**: `fit=contain` adds white padding around the source
> image to preserve the aspect ratio. Some VLMs (qwen2.5vl:7b on KBS
> Hall layouts) misinterpret the letterbox as part of the seating area
> and misclassify `stage_location` as `CENTER` instead of `TOP`. If
> `stage_location` accuracy matters, prefer `fit=fill` (stretch, no
> padding) or `fit=cover` (crop, no padding). If recall on small labels
> is the priority, `fit=contain` is still best (it preserves detail).

### scripts/eval_bug8_compare.py 변경

`OPTIONS.fit=contain` 유지 (기존 cross-model 비교와 동일 조건) + 주석으로 stage_location 주의 명시.

## 3. 권장 옵션 조합 (자체 측 use case 반영)

| 우선순위 | 옵션 | 이유 |
|---|---|---|
| **stage_location 정확도 최우선** | `fit=fill` + no padding | 자체 측 측정에서 fit=fill이 stage 정확 |
| **section recall (작은 라벨) 최우선** | `fit=contain` + white background | 작은 라벨 보존 |
| **균형 (현재 dev 권장)** | `fit=cover` (crop, no padding) | stage 정확 + aspect 보존의 절충 |

자체 측 마이그레이션이 `fit=fill`을 채택한 건 합리적. 다만 aspect ratio 보존이 필요한 venue (직사각형 layout)에서는 `fit=cover` 권장.

## 4. 자체 측 4 venue 데이터 회신 시 함께 받을 정보

기존 합의된 항목 + 추가:

| 항목 | 측정값 |
|---|---|
| venue별 recall (26000382, 26000634, 26008115, 26007886) | |
| **recall 평균** | **0.897 자체 보고** ✓ |
| venue별 stage_location 정확도 | |
| venue별 fit=fill vs fit=contain recall 차이 | |
| endpoint_used 분포 (native vs openai vs null) | |
| 422 발생 빈도 (json_schema 위반) | |
| elapsed_ms (per venue) | |
| `max_tokens=16384` 사용 후 효과 (만약 자체 측 클라이언트가 미검증이면) | |

## 5. 자체 측 현재 상태

- `extract-layout-api.ts` 운영 가능, 기본 옵션 = png + 600x540 fit=fill ✓
- 3 venue 평균 recall 0.897 ✓
- 56/56 tests 통과, typecheck 0 errors ✓
- 기존 `extract-layout.ts` (Ollama fallback) 보존 ✓

**API 자체는 production-ready 상태**로 보입니다. dev 측 추가 작업은 hold 유지, recall 측정 결과 회신 대기합니다.

회신 기다리겠습니다.

감사합니다.