#!/usr/bin/env python
"""Create deterministic laundering variants from real W08 trace JSONL files.

This script does not generate synthetic experiment results. It only rewrites existing
trace text into predefined stress-test inputs, preserving record IDs and provenance
metadata. Model-based paraphrases must be supplied as an external JSONL file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

EXTERNAL_CONDITIONS = {
    "paraphrase_second_model",
    "style_rewrite",
    "self_rewrite_with_non_candidate_llm",
}

LOCAL_CONDITIONS = {
    "identity_control",
    "cot_compression",
    "truncate_reasoning_to_final_steps",
    "answer_only_compression",
    "strip_reasoning_markers",
}

ALL_CONDITIONS = sorted(EXTERNAL_CONDITIONS | LOCAL_CONDITIONS)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} is not valid JSONL") from exc
    return rows


def extract_boxed(text: str) -> str | None:
    idx = text.rfind("\\boxed")
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    chars: list[str] = []
    for char in text[start:]:
        if char == "{":
            depth += 1
            if depth == 1:
                continue
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        chars.append(char)
    value = "".join(chars).strip()
    return value or None


def get_answer(record: dict) -> str | None:
    for key in ("answer", "gold", "final_answer"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value).strip()
    trace = str(record.get("trace", ""))
    boxed = extract_boxed(trace)
    if boxed:
        return boxed
    match = re.search(
        r"(?:final answer|answer)\s*(?:is|:)?\s*\$?([-0-9.,/]+)", trace, re.I
    )
    return match.group(1).strip() if match else None


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    pieces = re.split(r"(?<=[.!?。！？])\s+", normalized)
    return [piece.strip() for piece in pieces if piece.strip()]


def strip_markers(trace: str) -> str:
    text = re.sub(r"</?think>", " ", trace, flags=re.I)
    text = re.sub(r"\b(?:let'?s|we need to|I need to)\s+think\b", " ", text, flags=re.I)
    text = re.sub(r"\bstep\s+\d+\s*[:.)-]?", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def truncate_to_final_steps(trace: str, keep_sentences: int) -> str:
    sentences = split_sentences(strip_markers(trace))
    if len(sentences) <= keep_sentences:
        return " ".join(sentences)
    return " ".join(sentences[-keep_sentences:])


def answer_only(record: dict, allow_missing_answer: bool) -> str:
    answer = get_answer(record)
    if not answer:
        if allow_missing_answer:
            return ""
        record_id = record.get("id", "<missing-id>")
        raise SystemExit(
            f"Cannot make answer-only trace for {record_id}: missing answer"
        )
    return f"The final answer is \\boxed{{{answer}}}."


def external_lookup(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    rows = load_jsonl(path)
    output = {}
    for row in rows:
        key = str(row.get("id", ""))
        if not key:
            raise SystemExit(f"{path} contains a rewrite row without id")
        output[key] = row
    return output


def rewrite_trace(
    record: dict,
    condition: str,
    external_rows: dict[str, dict],
    keep_sentences: int,
    allow_missing_answer: bool,
) -> tuple[str, str]:
    trace = str(record.get("trace", ""))
    if condition == "identity_control":
        return trace, "identity"
    if condition == "strip_reasoning_markers":
        return strip_markers(trace), "remove-think-tags-and-step-markers"
    if condition == "cot_compression":
        compressed_keep = max(2, min(keep_sentences, 3))
        return (
            truncate_to_final_steps(trace, compressed_keep),
            f"compressed-chain-of-thought-keep-last-{compressed_keep}-sentences",
        )
    if condition == "truncate_reasoning_to_final_steps":
        return (
            truncate_to_final_steps(trace, keep_sentences),
            f"keep-last-{keep_sentences}-sentences",
        )
    if condition == "answer_only_compression":
        return answer_only(record, allow_missing_answer), "boxed-answer-only"
    if condition in EXTERNAL_CONDITIONS:
        record_id = str(record.get("id", ""))
        if record_id not in external_rows:
            raise SystemExit(
                f"Missing external rewrite for id={record_id} condition={condition}"
            )
        rewrite = external_rows[record_id]
        value = (
            rewrite.get("trace")
            or rewrite.get("rewritten_trace")
            or rewrite.get("text")
        )
        if not value:
            raise SystemExit(
                f"External rewrite for id={record_id} has no trace/rewritten_trace/text"
            )
        return str(value), f"external-{condition}"
    raise SystemExit(f"Unsupported condition: {condition}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", required=True, help="Raw trace JSONL with id/problem/trace fields"
    )
    parser.add_argument("--out", required=True, help="Output laundered trace JSONL")
    parser.add_argument("--condition", required=True, choices=ALL_CONDITIONS)
    parser.add_argument(
        "--external-rewrite-jsonl", help="Required for model-based rewrites"
    )
    parser.add_argument("--keep-sentences", type=int, default=6)
    parser.add_argument("--allow-missing-answer", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    out_path = Path(args.out)
    if args.condition in EXTERNAL_CONDITIONS and not args.external_rewrite_jsonl:
        raise SystemExit(f"{args.condition} requires --external-rewrite-jsonl")

    rows = load_jsonl(input_path)
    external_rows = external_lookup(
        Path(args.external_rewrite_jsonl) if args.external_rewrite_jsonl else None
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in rows:
            original_trace = str(record.get("trace", ""))
            new_trace, recipe = rewrite_trace(
                record,
                args.condition,
                external_rows,
                args.keep_sentences,
                args.allow_missing_answer,
            )
            output = dict(record)
            output["trace"] = new_trace
            output["laundering_condition"] = args.condition
            output["laundering_recipe"] = recipe
            output["original_trace_sha256"] = sha256_text(original_trace)
            output["laundered_trace_sha256"] = sha256_text(new_trace)
            output["original_n_chars"] = len(original_trace)
            output["laundered_n_chars"] = len(new_trace)
            handle.write(json.dumps(output, ensure_ascii=True) + "\n")
    print(f"Wrote {len(rows)} laundered traces -> {out_path}")


if __name__ == "__main__":
    main()
