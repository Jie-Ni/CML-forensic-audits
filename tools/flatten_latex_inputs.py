#!/usr/bin/env python3
"""Expand LaTeX \\input/\\include directives into a single .tex file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")


def strip_comment(line: str) -> tuple[str, str]:
    escaped = False
    for i, char in enumerate(line):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "%" and not escaped:
            return line[:i], line[i:]
        escaped = False
    return line, ""


def resolve_input(root: Path, current_dir: Path, name: str) -> Path:
    candidate = Path(name.strip())
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.extend([root / candidate, current_dir / candidate])

    expanded: list[Path] = []
    for path in candidates:
        expanded.append(path)
        if path.suffix == "":
            expanded.append(path.with_suffix(".tex"))

    for path in expanded:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(f"Cannot resolve LaTeX input {name!r} from {current_dir}")


def expand_file(path: Path, root: Path, seen: set[Path]) -> str:
    path = path.resolve()
    if path in seen:
        raise RuntimeError(f"Recursive LaTeX input detected: {path}")
    seen.add(path)

    chunks: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        code, comment = strip_comment(line)

        def replace(match: re.Match[str]) -> str:
            input_path = resolve_input(root, path.parent, match.group(1))
            expanded = expand_file(input_path, root, seen)
            rel = input_path.relative_to(root).as_posix()
            return f"% BEGIN expanded input: {rel}\n{expanded}% END expanded input: {rel}\n"

        chunks.append(INPUT_RE.sub(replace, code) + comment)

    seen.remove(path)
    return "".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    input_path = args.input if args.input.is_absolute() else root / args.input
    output_path = args.output if args.output.is_absolute() else root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(expand_file(input_path, root, set()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
