**제목**: [vision-ocr-detect] feature-bugs-followup-extra-4.md 회신 — schema-prompt mismatch 발견 + null-tolerance fix

**본문**:

자체 측 followup-extra-4 §3 schema-prompt mismatch 진단 정확합니다. **제 A1 fix (`95537e8`)가 회귀 유발** — guard clause "do not invent or guess"가 model output 변경시켜 `"special": null` 명시, requester 측 json_schema는 null 불허 → 422 cascade. 자체 측 mean recall 0.897 → 0.518 (json_schema mode 한정, lenient mode는 baseline 유지).

## 1. 회귀 인정

제 prompt fix 의도: contamination 차단 (alphabetic 환각 제거).
부작용: model behavior 변화 → 모든 section에 `"special": null` 명시 → schema fail.
자기 fix가 다른 surface 회귀 trigger. 죄송합니다.

## 2. §4 Option A 진행 — 실제 fix 경로 명시

자체 측 §4 Option A 제안: `detect.py`의 `special` 필드 타입을 nullable로 변경.

**명확화**: `special` 필드는 **requester 측 json_schema 스펙**에 정의되어 있고, 서버 코드(`detect.py` 등)에는 존재하지 않습니다. 따라서 `detect.py`의 필드를 변경하는 것은 구조적으로 불가.

대신, **동일 효과를 내는 server-side fix** 적용 — json_schema mode schema validation의 **null-tolerance retry**:

```
1차 validation: 명시적 null → schema 위반 → fail
retry: `"key": null` 항목을 재귀적으로 제거 후 재검증
성공 시 → cleaned dict 반환, raw text 보존
실패 시 → 422 (그대로)
```

### 회귀 방지 동작 보장

| 시나리오 | 동작 |
|---|---|
| schema가 명시적으로 null 허용 (`type: ["string", "null"]`) | 1차 통과, retry 미실행. 변경 없음. |
| Optional 필드가 `null`로 emit | 1차 fail → retry drop → 2차 통과. 200. |
| Required 필드가 `null`로 emit | 1차 fail → retry drop → 2차 fail (required 위반). 422. |
| schema에 null 아닌 enum만 정의된 필드에 `null` | 1차 fail → retry drop → 2차 통과 (optional이면). 200. |

Raw `text` 필드는 **항상 보존** — cleaning은 `parsed`에만 영향.

## 3. 구현 (커밋 `8997d55`)

### `src/vision_ocr_detect/api/detect.py`

```python
def _drop_null_fields(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_null_fields(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_null_fields(item) for item in obj]
    return obj
```

`_validate_against_schema` retry step 추가 (1차 fail 시 cleaned dict로 재시도, 2차 fail이면 None 반환).

### Tests (3개 추가, 120/120 통과)

- `test_response_format_json_schema_drops_explicit_null_for_optional_field` (positive)
- `test_response_format_json_schema_required_null_still_returns_422` (negative)
- `test_response_format_json_schema_null_in_array_item_is_dropped` (array 내부 null도 처리)

### README

json_schema mode 문서에 **Null-tolerance retry** 절 추가.

## 4. 자체 측 §5 workaround (Option ii `json-quirks`) 상태

자체 측 잠정 선택 (Option ii: client-side `normalizeNullSpecials`) — 본 회신 fix 적용 후 **불필요**. 422 cascade 해결되어 lenient fallback 회피 가능. 단, 회귀 시 안전망으로 보존 권장.

자체 측 결정 사항:
- Option ii 적용 보류 권장 (서버 fix로 처리됨)
- 만약 자체 측 production에 즉시 배포 시: 서버 commit `8997d55` pull 후 측정 재실행 → json_schema mode = lenient mode baseline 0.897 회복 예상

## 5. §7 §1 보강 — 추가 회귀 없음

자체 측 §7 *"양측 fix 방향 동일. 회귀 원인은 prompt가 아닌 schema-prompt mismatch"* 진단 동의.

26000382 override recall 0.037 (§1 falsification) 여전히 유효. 1-pass trade-off는 qwen2.5vl:7b 단일 모델 한계.

## 6. 자체 측 verify 권고

회신 후 자체 측 재측정 부탁드립니다:

```bash
# json_schema mode (현재 회귀 측정, baseline 0.897 회복 검증)
$ measure-recall.ts --format json_schema

# lenient mode (대조군)
$ measure-recall.ts --format json
```

기대 결과: 두 모드 모두 mean recall 0.897 ± noise. json_schema mode 회귀 종료.

## 7. 정리

| 항목 | 상태 |
|---|---|
| §3 root cause (schema-prompt mismatch) | ✓ 자체 측 진단 정확 |
| §4 Option A 의도 (null tolerance) | ✓ 구현 (커밋 `8997d55`) |
| §4 Option A 표면 (`detect.py` 필드 변경) | ✗ 불가 (필드 부재) — 동등 효과로 구현 |
| Tests | 120/120 ✓ |
| README | null-tolerance retry 절 추가 |
| 자체 측 §5 workaround | 서버 fix로 처리 — Option ii 보류 권장 |

협업 trust 회복 위해 §1 회귀 + §3 진단 모두 즉각 처리했습니다. 회신 감사합니다.