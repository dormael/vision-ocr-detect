**제목**: [vision-ocr-detect] feature-bugs-followup.md 회신 — Bug 7 재발 분석 결과 + hotfix

**본문**:

안녕하세요, hotfix 검증 결과 잘 받았습니다. **Bug 7 재발 보고**가 정확히 일치해서 자체 환경에서 재현 후 진단·수정했습니다.

## 진단

자체 환경에서 요청자 시나리오 그대로 재현:

```bash
curl -X POST localhost:8000/api/detect \
  -F 'profile=interpark-layout' \
  -F 'image=@fixtures/layouts/26000634.gif' \
  -F 'options={"response_format":"json","temperature":0.0}'
```

**결과**: `parsed: None`, `text`에 ```json fence 그대로 (커밋 `8bf79fc` fence strip이 동작하지 않는 것처럼 보임).

**근본 원인 분석**:
- fence strip은 정상 동작 (regex `_FENCE_RE`가 매칭됨)
- `_strip_markdown_fence` 이후 `json.loads` 호출이 **다른 라인에서 실패**
- 확인: line 39 `"horizontal_alignment": +2` ← VLM이 signed integer (`+N`) 출력
- Python `json.loads`는 RFC 8259 따라 leading `+` 거부
- 즉, **Bug 7 (fence strip)은 해결됐지만, 별도 JSON quirk (`+N`)이 빈번**해서 동일 증상으로 보임

## 수정 (커밋 `d8c3cdd`)

lenient 파서 강화:

```python
_PLUS_INT_RE = re.compile(r"(?<![\w.\"])\+(\d)")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_DOUBLE_COMMA_RE = re.compile(r",\s*,")

def _normalize_json_quirks(text: str) -> str:
    s = _PLUS_INT_RE.sub(r"\1", text)        # ": +N" → ": N"
    s = _DOUBLE_COMMA_RE.sub(",", s)          # ",," → ","
    s = _TRAILING_COMMA_RE.sub(r"\1", s)      # ", }" → " }"
    return s
```

- 새 helper `_lenient_parse_json(text)`: fence strip + 정규화 + json.loads
- `text` 필드는 **byte-for-byte 보존** (클라이언트 디버깅용)
- `response_format: "json"` 모드와 `response_format: "json_schema"` 모드 둘 다 적용
- `json_schema` 모드는 schema 검증은 그대로 — 정규화는 parse 단계만

## 자체 검증

라이브 (요청자 시나리오 그대로):

| 항목 | hotfix 전 | hotfix 후 |
|---|---|---|
| fence strip | ✓ 동작 | ✓ 동작 |
| `: +N` 처리 | ✗ parsed=null | ✓ parsed 정상 |
| trailing comma | ✗ parsed=null | ✓ parsed 정상 |
| double comma | ✗ parsed=null | ✓ parsed 정상 |

테스트 102/102 통과 (lenient 6개 신규 + fence 기존 2개).

## 마이그레이션 재평가

**결론: client-side fallback parse 코드 제거 가능**.

| 단계 | 권장 |
|---|---|
| 1. 기존 client-side regex (`/```json\s*([\s\S]*?)\s*```/`) | **제거 가능** — 서버 fence strip이 처리 |
| 2. 기존 client-side `+숫자` / trailing comma 정규화 | **제거 가능** — 서버 lenient 파서가 처리 |
| 3. `apply-corrections` 후처리 | **유지 권장** — 환각 섹션 추가 등 VLM 한계는 정규화로 해결 안 됨 |

남은 `apply-corrections` 워크플로우는 VLM이 빠뜨린 section을 사람이 보정하는 의미적 작업이라 서버 API 영역 밖.

## 우선순위 합의 (요청자 측)

요청자 권장 순서: **#7 tokens_in/out → OllamaProvider native → #6 batch**

자체 의견:
- **#7 tokens_in/out**: 우선 진행 동의. `response_format=json_schema`와 함께 가면 호출 단위 usage 추적 자연스러움.
- **OllamaProvider native**: granite3.2-vision 등 다중 모델 옵션 확보 가치 있음. `format: "openai" | "native"` 같은 옵션으로 모델별 분기 가능.
- **#6 batch**: 단일 venue 단일 image 워크플로우라면 후순위 동의.

진행 순서 합의 부탁드립니다. **#7부터 시작**한다고 가정하고 별도 회신 시 plan mode로 들어가겠습니다.

감사합니다.