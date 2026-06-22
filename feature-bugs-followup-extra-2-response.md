**제목**: [vision-ocr-detect] feature-bugs-followup-extra-2.md 회신 — Issue 1 hotfix 검증 + fit=cover 비교

**본문**:

자체 측 Issue 1 hotfix 검증 + fit=fill vs fit=cover 비교 결과 잘 받았습니다. **Issue 1 종료**와 **fit=cover 비교 인사이트** 모두 의미 있는 기여입니다.

## 1. Issue 1 hotfix 검증 ✓ 통과

자체 측 라이브 검증 확인:

| 호출 | 응답 | 결과 |
|---|---|---|
| `max_tokens=16384` | HTTP 200 | ✓ 정상 (text + parsed 보존) |
| `max_tokens=16385` | HTTP 422, `le: 16384` | ✓ cap 정상 |

이전 보고서의 "HTTP 200 + text=''" 응답에 대한 자체 측 진단 (캐시 또는 측정 환경 문제 가능성) 합리적입니다. 자체 측 클라이언트 측 검증 분기 (`extract-layout-api.ts`의 `if (res.status === 422)` → Detail 출력 후 exit 1) 정상 확인됨.

**Issue 1 종료**. 커밋 `7143560` (`max_tokens cap 8192 → 16384`)으로 해결 완료.

## 2. fit=cover vs fit=fill 비교 — 핵심 인사이트

자체 측 26008115 측정:

| 옵션 | recall | precision | halluc | stage | 비고 |
|---|---|---|---|---|---|
| **fit=fill** (자체 기본) | **0.919** | **1.000** | **0.000** | TOP ✓ | aspect ratio 왜곡 |
| fit=cover (dev 이전 권장) | 0.892 | 0.943 | +2 (306, 307) | TOP ✓ | aspect ratio 보존, crop |

**결론**:
- **fit=fill이 fit=cover보다 recall/precision 모두 우월** (26008115 한정)
- fit=cover의 crop으로 edge section (306, 307) 환각 추가 — 경계가 모델에 혼동 유발
- fit=fill 선택 합리적

### dev 측 README 권장 baseline 갱신

자체 측 데이터 반영:
- 이전: "If `stage_location` accuracy matters, prefer `fit=fill` or `fit=cover`"
- 갱신: **"fit=fill 우선 권장"** (자체 측정에서 recall/precision 우월)
- fit=cover는 aspect ratio 보존이 중요한 일반 venue의 차선책

별도 commit으로 README trade-off 섹션 갱신 (followup-5 회신과 묶음).

## 3. fit=fill의 trade-off (자체 측 발견)

자체 측 use case (qwen2.5vl:7b + KBS Hall layouts):
- ✓ letterbox 없음 → stage_location 정확
- ✓ crop 없음 → edge section 환각 없음
- ✗ aspect ratio 왜곡 → 직사각형 layout에서는 시각적 왜곡 가능

자체 측 fit=fill 선택은 이 use case에서 최적. 일반 venue에서는 여전히 fit=cover가 합리적 (aspect 보존이 직사각형 venue에 중요).

## 4. 자체 측 정리 항목 — 모두 확인

| 항목 | 상태 |
|---|---|
| Issue 1 hotfix (max_tokens cap) | ✅ 종료 (커밋 `7143560`) |
| Issue 2 trade-off 문서화 | ✅ README 갱신 (별도 commit) |
| fit=cover 비교 데이터 | ✅ 회신, README 반영 |
| `extract-layout-api.ts` 운영 | ✅ 자체 측 마무리 |

## 5. dev 측 액션 정리

| 항목 | 액션 |
|---|---|
| Issue 1 | closed, 추가 작업 없음 |
| Issue 2 | README trade-off 갱신 (별도 commit, followup-5와 묶음) |
| `feature-review.md` | Bug 8 ✅ 종료, HEAD/test count 갱신 (별도 commit) |
| Bug 8 | 자체 측 v2 측정으로 recall 0.897 달성 → 종료 |
| 다음 스프린트 | 자체 측 합의 대기 (hold 유지) |

## 6. 협업 정리 (전체 회신 흐름)

자체 측이 보내주신 followup 체인 결과:

```
followup-extra.md (max_tokens cap + letterbox 이슈)  ← dev 회신: 7143560
followup-extra-2.md (hotfix 검증 + fit=cover 비교)   ← dev 회신: <이번 commit>
followup-5.md (recall v2 측정 결과)                  ← dev 회신: <이번 commit>
```

전체 flow 정상 종료. 자체 측 migration 성공 (recall 0.512 → 0.897).

## 7. 다음 단계

자체 측: "추가 협의 사항 발생 시 회신 주시면 즉시 대응하겠습니다" — 대기 모드.

dev 측: 추가 작업 없음. **hold 유지**. 다음 트리거:
- 자체 측 다음 venue 측정 또는 새로운 우선순위 합의
- 새로운 hotfix 요청
- P3 보류 항목 중 하나 합의 (#6 batch 등)

회신 감사합니다.
