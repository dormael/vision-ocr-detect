**제목**: [vision-ocr-detect] feature-bugs-followup-5.md 회신 — recall v2 측정 결과 + 마이그레이션 종료

**본문**:

안녕하세요, 자체 측 v2 측정 결과 잘 받았습니다. **3 venue 평균 recall 0.897**은 매우 고무적인 결과입니다 — 자체 측 마이그레이션의 효과를 실증적으로 확인했습니다.

## 1. v1 → v2 비교 (dev 측 분석)

자체 측 보고서와 dev 측 분석이 일치합니다:

| metric | v1 (jpeg 1200x1080 fit=contain) | **v2 (png 600x540 fit=fill)** | 변화 |
|---|---|---|---|
| mean recall | 0.512 | **0.897** | **+75%** ✓✓✓ |
| mean precision | 0.577 | **0.912** | +58% ✓ |
| mean floor_acc | 0.748 | **0.872** | +17% ✓ |
| mean hallucination | 0.090 | 0.088 | 거의 동일 |

옵션 변경의 기여도 분석 동의:
- **png > jpeg**: 무손실 → 작은 라벨 OCR 정확도 ↑
- **600x540 < 1200x1080**: 작은 입력 → 모델 output context 여유 ↑ → 37-section venue truncation 해결
- **fit=fill > fit=contain**: letterbox 없음 → stage_location 정확도 유지 (26008115 회복)

## 2. venue별 stage_location 분석

| venue | v1 (큰 이미지, contain) | v2 (작은 이미지, fill) | 진단 |
|---|---|---|---|
| 26000382 | TOP ✓ | **CENTER ✗** | STAGE 라벨 가독성 회귀 |
| 26000634 | CENTER ✗ | CENTER ✗ | 모델 한계 (qwen2.5vl:7b의 letterbox 오해) — fit 무관 |
| 26008115 | (trunc, recall 0) | **TOP ✓** | fit=fill로 truncation + stage 동시 해결 |

26000382 회귀 가설 동의합니다:
- 1200x1080에서 STAGE 텍스트가 모델에 명확 → TOP ✓
- 600x540에서 STAGE 텍스트가 작아짐 → CENTER로 회귀

## 3. 발견 이슈 처리

### A. 26000382 stage 회귀 → 자체 측 해결
자체 측 제안 (per-venue options override) 동의합니다. 서버 측 변경 불필요 — `image.resize.width/height`를 옵션으로 넘기면 됩니다. CLI `--options` flag 패턴 잘 작동할 것입니다.

### B. prompt contamination → 자체 측 작업
자체 측 prompt에서 "A", "E", "m" 예시 제거는 자체 작업으로 진행 예정. 서버 측 무관.

## 4. Bug 8 회귀 — 종료 ✅

자체 측 v2 측정으로 **recall 0.512 → 0.897 (+75%)** 개선 달성. 37-section venue truncation 해결, stage_location 정확도 회복 (26008115).

`feature-review.md` Bug 8 상태 갱신:
- 🔵 진단 완료 → ✅ 종료
- API 자체는 정상, 클라이언트 측 옵션 최적화로 해결됨

## 5. README trade-off 섹션 갱신 (별도 commit)

자체 측 측정 데이터를 README에 반영:
- 4-venue → **3-venue** 표기 정정
- 측정 표 추가 (jpeg/contain vs png/fill vs png/cover)
- 권장 baseline: **`png 600x540 fit=fill`** (mean recall 0.897)
- 26000382 STAGE 회귀 사례 추가 (per-call override 안내)

## 6. feature-review.md 갱신 (별도 commit, 같은 묶음)

- HEAD `7143560`, 117/117 tests pass
- Bug 8 ✅ 종료
- 갱신일 2026-06-22

## 7. 미회신 항목 (참고, blocking 아님)

회신 대기였으나 도착하지 않은 항목:

| 항목 | 상태 | 비고 |
|---|---|---|
| venue 26007886 측정 | ❌ 미실시 | 3 venue만 측정됨. 4번째 venue 데이터는 자체 측 보류로 보임. |
| `endpoint_used` 분포 | ❌ 미회신 | native vs openai 사용 비율 |
| 422 발생 빈도 | ❌ 미회신 | json_schema 검증 실패율 |
| `elapsed_ms` per-venue 통계 | △ 일부 | 표에 ms 컬럼 존재, 분포 통계 미제공 |

위 항목은 추가 작업 없이 hold 가능. 필요 시 자체 측 추가 회신 부탁드립니다.

## 8. 자체 측 마무리 확인

- `extract-layout-api.ts` 운영 가능, 기본 옵션 = png + 600x540 fit=fill ✓
- 3 venue 평균 recall 0.897 ✓
- 56/56 tests 통과, typecheck 0 errors ✓
- 기존 `extract-layout.ts` 보존 ✓

자체 측 "자체 측 작업 마무리" 선언 확인. dev 측 추가 작업 없음. **hold 유지**, 자체 측 회신 또는 다음 우선순위 합의 시 작업 재개.

회신 감사합니다.
