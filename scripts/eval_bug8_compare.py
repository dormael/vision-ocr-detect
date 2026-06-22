"""Bug 8 cross-model evaluation.

Compares the layout-extraction quality of multiple vision-capable models
against the same ground truth (fixtures/expected/26000634.expected.json).
Single baseline: API + fit=contain 1200x1080 + jpeg (the requester's
best-known config).

Outputs a markdown table on stderr and per-model JSON on stdout.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
GIF = FIX / "layouts" / "26000634.gif"
PROMPT_FILE = FIX / "profiles" / "interpark-layout.json"
EXPECTED_FILE = FIX / "expected" / "26000634.expected.json"

OLLAMA_URL = "http://localhost:11434"
API_URL = "http://localhost:8000"

# Single shared config: the requester's "best so far" per the bug report.
# NOTE: fit=contain adds white letterbox padding. The requester's
# 4-venue recall measurement showed this caused qwen2.5vl:7b to
# misclassify stage_location on KBS Hall layouts (2/3 venues → CENTER
# instead of TOP). The script keeps fit=contain for backward compat
# with the original cross-model comparison; production code that cares
# about stage_location should prefer fit=fill (stretch) instead.
OPTIONS = {
    "temperature": 0.0,
    "max_tokens": 4096,
    "response_format": "json",
    "image": {
        "format": "jpeg",
        "resize": {"width": 1200, "height": 1080, "fit": "contain", "background": "#ffffff"},
    },
}


def _load_fixtures() -> tuple[bytes, str, dict]:
    raw = GIF.read_bytes()
    profile = json.loads(PROMPT_FILE.read_text())
    expected = json.loads(EXPECTED_FILE.read_text())
    return raw, profile["prompt"], expected


def _parse_vlm_json(text: str) -> dict | None:
    import re

    fence = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
    m = fence.match(text.strip())
    body = m.group(1) if m else text
    norm = body
    norm = re.sub(r":\s*\+(\d)", r": \1", norm)
    norm = re.sub(r",\s*([}\]])", r"\1", norm)
    norm = re.sub(r",\s*,", r",", norm)
    try:
        return json.loads(norm)
    except Exception:
        return None


# ----------------------------------------------------------------------
# Callers
# ----------------------------------------------------------------------


def call_via_profile_overrides(
    raw_gif: bytes, prompt: str, model: str
) -> dict:
    """Use the existing interpark-layout profile + profile_override to swap model."""
    files = {"image": ("26000634.gif", io.BytesIO(raw_gif), "image/gif")}
    data = {
        "profile": "interpark-layout",
        "options": json.dumps({**OPTIONS, "profile_override": {"model": model}}),
    }
    with httpx.Client(timeout=300.0) as c:
        r = c.post(f"{API_URL}/api/detect", files=files, data=data)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return {
        "model": model,
        "status": r.status_code,
        "elapsed_ms": body.get("elapsed_ms"),
        "raw": body.get("text"),
        "parsed": body.get("parsed"),
    }


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------


def _name(s: dict) -> str:
    return str(s.get("name", "")).strip()


def score(parsed: dict | None, expected: dict) -> dict:
    if not parsed or not isinstance(parsed, dict):
        return {
            "parsed_ok": False,
            "stage_pred": None,
            "stage_ok": False,
            "n_pred": 0,
            "n_expected": len(expected["sections"]),
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "recall": 0.0,
            "precision": 0.0,
            "hallucination_rate": 0.0,
            "floor_ok": 0,
            "floor_total": 0,
            "floor_accuracy": 0.0,
        }

    pred_sections = parsed.get("sections") or []
    pred_names = [_name(s) for s in pred_sections]
    exp_names = [_name(s) for s in expected["sections"]]
    exp_set = set(exp_names)
    pred_set = set(pred_names)

    tp = len(exp_set & pred_set)
    fp = len(pred_set - exp_set)
    fn = len(exp_set - pred_set)
    n_pred = len(pred_set)
    n_exp = len(exp_set)

    floor_ok = floor_total = 0
    exp_by_name = {_name(s): s for s in expected["sections"]}
    for ps in pred_sections:
        nm = _name(ps)
        if nm in exp_by_name:
            floor_total += 1
            if ps.get("floor") == exp_by_name[nm].get("floor"):
                floor_ok += 1

    stage_pred = parsed.get("stage_location")
    stage_ok = stage_pred == expected.get("stage_location")

    return {
        "parsed_ok": True,
        "stage_pred": stage_pred,
        "stage_expected": expected.get("stage_location"),
        "stage_ok": stage_ok,
        "n_pred": n_pred,
        "n_expected": n_exp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": round(tp / n_exp, 3) if n_exp else 0.0,
        "precision": round(tp / n_pred, 3) if n_pred else 0.0,
        "hallucination_rate": round(fp / n_pred, 3) if n_pred else 0.0,
        "floor_ok": floor_ok,
        "floor_total": floor_total,
        "floor_accuracy": round(floor_ok / floor_total, 3) if floor_total else 0.0,
        "missing": sorted(exp_set - pred_set),
        "extra": sorted(pred_set - exp_set),
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


MODELS_TO_COMPARE = [
    "qwen2.5vl:7b",      # current default; the one in the bug report
    "deepseek-ocr:3b",   # OCR-specific
    "glm-ocr:latest",    # OCR-specific
    "granite3.2-vision:2b",  # smaller vision model
    "minicpm-v:8b",      # alternative VLM
]


def main() -> int:
    raw_gif, prompt, expected = _load_fixtures()

    rows = []
    for model in MODELS_TO_COMPARE:
        out = call_via_profile_overrides(raw_gif, prompt, model)
        # Server's lenient parser only handles fence stripping; for scoring
        # we also apply `+`/trailing-comma normalizations locally so we
        # measure what the VLM *meant*, not just what `json.loads` accepts.
        server_parsed = out.get("parsed")
        if server_parsed is None and out.get("raw"):
            server_parsed = _parse_vlm_json(out["raw"])
        s = score(server_parsed, expected)
        rows.append({"model": model, **out, **s})
        sys.stderr.write(
            f"  done: {model:30} HTTP={out['status']} parsed={s['parsed_ok']} "
            f"recall={s['recall']} stage={s.get('stage_pred')}\n"
        )

    md = [
        "",
        "## Bug 8 cross-model 평가 (fit=contain + jpeg baseline)",
        "",
        "Expected: stage_location=TOP, 24 sections.",
        "",
        "| Model | HTTP | parsed | recall | precision | 환각 | floor_acc | stage_pred | TP/FP/FN |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['model']} | {r['status']} | "
            f"{'✓' if r['parsed_ok'] else '✗'} | "
            f"{r['recall']} | {r['precision']} | {r['hallucination_rate']} | "
            f"{r['floor_accuracy']} | {r.get('stage_pred')} | "
            f"{r['tp']}/{r['fp']}/{r['fn']} |"
        )
    sys.stderr.write("\n".join(md) + "\n")

    print(json.dumps({"models": rows, "expected_section_count": len(expected["sections"])}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())