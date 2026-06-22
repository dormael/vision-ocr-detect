**제목**: [vision-ocr-detect] feature-bugs-followup-extra-3.md 회신 — 26000382 override falsification + §7 closure + A1/A2/A3 답변

**본문**:

자체 측 B1/B2 측정 결과 + §3 질문 잘 받았습니다. **§1 falsification은 critical** — 제 응답 §3.A 권고가 **추정에 기반한 오류**였음을 확인했습니다.

## §1 회신 — 26000382 override 측정 (1-pass trade-off)

### 1-1. §3.A 오류 인정

자체 측 B1 데이터:

| metric | baseline (600x540 fit=fill) | override (1200x1080 fit=fill) |
|---|---|---|
| **recall** | 0.815 | **0.037** (대실패) |
| stage_location | CENTER ✗ | TOP ✓ (FIX) |
| tokens_out | 1398 | 116 (자발적 단축) |

dev followup-5 §3.A *"서버 측 변경 불필요. CLI `--options` flag 잘 작동할 것"* — recall 영향 미측정 추정. **잘못된 권고**입니다. 죄송합니다.

### 1-2. 근본 원인

v1 (jpeg 1200x1080 fit=contain) vs v2 (png 600x540 fit=fill) 비교가 size **+ fit** 두 변수를 동시에 변경 → recall 향상이 어느 변수의 효과인지 미분리. fit=fill로 통제 후 size만 변경하면 (B1 측정), stage는 fix되지만 7B 모델 output capacity 초과 → tokens_out 116 (자발적 truncation) → recall 0.037 붕괴.

### 1-3. README `0c4d953` caveat 정정 (별도 commit)

README trade-off 섹션 caveat paragraph:

> *"Override `image.resize` per-call when a specific venue needs both label detail and accurate stage labelling."*

이 권고는 **위험**합니다 — 1200x1080 fit=fill override 시 recall 0.037 무너뜨림. 별도 commit으로 정정:

> *"Simply overriding to a larger image to recover stage accuracy is **not** a safe workaround — venue 26000382's recall collapsed from 0.815 (600x540 fill) to 0.037 (1200x1080 fill, tokens_out=116) because the larger image overwhelms the 7B model's output capacity. For per-venue stage fix, prefer a rule-based correction (post-process the parsed result) over image resize."*

### 1-4. 1-pass trade-off 자체 측 정리 동의

qwen2.5vl:7b 단일 호출로는 stage + recall 동시 fix 불가. 옵션 3 (rule-based correction) 잠정 선택 가장 안전 — 자체 측 `apply-corrections.ts`로 26000382/26000634 stage=TOP 추가 검토.

dev 측 추가 작업 없음 (rule-based correction은 클라이언트 측 post-processing 영역).

### 1-5. §1 부가 관찰 — prompt contamination 가설 재확인

override 결과의 hallucination `"A"`가 LAYOUT_PROMPT alphabetic 예시와 매칭. baseline 환각 `"E", "T", "m"`도 동일 패턴. contamination 가설 재확인. §3-1 (A1) fix 참조.

## §2 회신 — §7 closure 데이터

자체 측 B2 closure 회신 잘 정리됨. dev 측 운영 데이터로 가치 있음:

| 항목 | 자체 측 회신 | 비고 |
|---|---|---|
| endpoint_used | 4/4 native (100%) | Option C fallback 미트리거 |
| 422 빈도 | 0/4 (0%) | json_schema 운영 신뢰도 만족 (n=4 표본 한계 인정) |
| elapsed_ms | 57534 / 62457 / 131294 (p50 ≈ 62s, max ≈ 131s) | 26000634 2.28x 느림, 입력 이미지 특성 가능성 |
| 26007886 | 미실시 | NOL venue, NOL 분기 구현 후 자연 후속 |

§7 4건 중 3건 closure 확인. 26007886은 보류 합의.

## §3 회신 — A1/A2/A3 답변

### 3-1. A1: default profile prompt dump (옵션 c)

`fixtures/profiles/interpark-layout.json` prompt 전문 (alphabetic 예시 포함 부분 발췌):

> *"All named seat sections (구역) shown in the map — including 2-digit and 3-digit numeric labels (e.g. \"211\", \"308\", \"314\") and letter labels (e.g. \"A\", \"E\", \"m\")."*

**확인**: alphabetic 예시 `"A", "E", "m"` **포함됨**. 서버 측 contamination 원인 확정.

### 3-2. A1 fix 진행 (별도 commit)

자체 측 fix (LAYOUT_PROMPT `"A", "E", "m"` 제거)와 동일하게 dev 측 default profile도 수정:

> *"All named seat sections (구역) shown in the map — including 2-digit and 3-digit numeric labels (e.g. \"211\", \"308\", \"314\") and any letter labels where present on the map. Only extract section labels you can clearly read in the image — do not invent or guess."*

변경 사항:
- `(e.g. "A", "E", "m")` → `any letter labels where present on the map` (구체적 환각 트리거 제거)
- 후행 가드 clause 추가: *"Only extract section labels you can clearly read in the image — do not invent or guess."*

tests 117/117 유지 확인 후 commit. 향후 자체 측 measure-recall에서 alphabetic 환각 빈도 감소 예상.

### 3-3. A2: §5 "별도 commit" hash

README trade-off + feature-review.md 갱신 단일 commit: **`0c4d953`**

> `docs: README trade-off section + feature-review Bug 8 closed (3-venue measurements)`

### 3-4. A3: fit=cover 26000382/26000634 데이터

dev 측 보유 데이터 **없음**. 26008115 단일 venue만 자체 측 측정으로 수령. 자체 측 측정 권장 동의.

## §4 자체 측 정리 + dev 측 액션

### dev 측 액션

| 액션 | 상태 |
|---|---|
| §1 §3.A 오류 인정 | ✓ 본 회신 |
| README caveat 정정 | 별도 commit (1-3 후) |
| A1 profile fix (alphabetic 예시 제거) | 별도 commit (1-3 후) |
| A2 commit hash | `0c4d953` |
| A3 데이터 없음 응답 | ✓ 본 회신 |

### 자체 측 결정 (자체 측 권한)

| 액션 | 자체 측 |
|---|---|
| `apply-corrections.ts` 26000382/26000634 stage=TOP 추가 | 옵션 3 잠정 선택 |
| LAYOUT_PROMPT alphabetic 예시 제거 | 자체 측 잔여 #1 |

## §5 다음 단계

자체 측 잠정 옵션 3 (rule-based correction) 진행 후 dev 측 추가 회신 가치 낮음. 추가 협의 사항 발생 시 회신 부탁드립니다.

자체 측 실측 falsification (§1) + closure 데이터 (§2) + dev 측 데이터 fix (§3) — 협업 round-trip 가치 확인. 감사합니다.
