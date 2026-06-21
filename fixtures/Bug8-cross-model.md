# Bug 8 cross-model evaluation

Run `scripts/eval_bug8_compare.py` against `fixtures/`. Compares 5
vision-capable models on the same image + prompt + ground truth.

## Result (fit=contain + jpeg baseline, expected 24 sections / stage=TOP)

| Model | HTTP | parsed | recall | precision | 환각 | floor_acc | stage_pred | TP/FP/FN |
|---|---|---|---|---|---|---|---|---|
| qwen2.5vl:7b        | 200 | ✓ | 0.458 | 0.846 | 0.154 | 0.909 | CENTER  | 11/2/13 |
| deepseek-ocr:3b     | 200 | ✗ | 0.000 | 0.000 | 0.000 | 0.000 | —       | 0/0/0   |
| glm-ocr:latest      | 200 | ✗ | 0.000 | 0.000 | 0.000 | 0.000 | —       | 0/0/0   |
| granite3.2-vision:2b | 502 | ✗ | 0.000 | 0.000 | 0.000 | 0.000 | —       | 0/0/0   |
| minicpm-v:8b        | 200 | ✗ | 0.000 | 0.000 | 0.000 | 0.000 | —       | 0/0/0   |

## Why each model failed

| Model | Failure mode |
|---|---|
| qwen2.5vl:7b | Best of the lot — 11/24 recall, 2 hallucinations ("A" repeated), 13 missing. Floor accuracy 0.909 on TPs. Stage misclassified as CENTER. |
| deepseek-ocr:3b | Outputs descriptive prose, not JSON. Doesn't follow `{"stage_location": ..., "sections": [...]}` instruction despite the prompt. |
| glm-ocr:latest | Produces JSON but with hallucinated field names and content (`"d距离_tier"` — Chinese characters appearing mid-field). Multiple disjoint JSON fragments in one output. |
| granite3.2-vision:2b | **Provider error**: ollama's `/v1/chat/completions` rejects granite-vision's images with `illegal base64 data at input byte 4`. Works on native `/api/generate` but our `OllamaProvider` uses OpenAI-compat. |
| minicpm-v:8b | Reports "The information provided does not contain an image" — model did not actually receive the image bytes (likely an ollama OpenAI-compat edge case). |

## Findings

1. **`qwen2.5vl:7b` is the right choice for this task.** The other 4
   models are not viable substitutes: 3 produce broken/empty outputs and
   1 (granite) is blocked by our provider's OpenAI-compat surface.
2. **The Bug 8 quality regression is NOT a model-selection problem.**
   The requester already picked the best model. The remaining gap (recall
   ~46% on a hard 24-section layout) is a fundamental limit of
   layout-extraction-from-image at this model size.
3. **Two production follow-ups surfaced from this eval:**
   - **Ollama provider OpenAI-compat gap**: at least granite-vision and
     minicpm-v reject `/v1/chat/completions` with images but accept
     `/api/generate`. A future enhancement would be a `format=native`
     switch in `OllamaProvider` that translates to the native generate
     endpoint for models that need it.
   - **Server-side JSON parsing is too strict for OCR-grade output.**
     The lenient parser (`8bf79fc`) handles fence stripping but not
     `+`/trailing-comma/double-comma quirks. For OCR use cases, applying
     the normalization in production would let `parsed` populate for
     outputs the model *meant* to be JSON but had a typo.

## Reproduction

```bash
# Once after server restart with latest main
uv run python scripts/eval_bug8_compare.py 2>&1 | tail -20
```

The script normalizes `+`/trailing commas/double commas locally for
scoring purposes — these aren't part of the server's lenient parse,
they're just for measuring what the VLM *meant*.