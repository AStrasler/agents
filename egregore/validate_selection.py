#!/usr/bin/env python3
"""Validate ``egregore/selection.yaml``.

The manifest points at upstream files. It does not copy them. This script
checks that the file is well-formed in the YAML subset below and that every
path exists inside the repository. The standard library is the only dependency.

YAML subset:

- UTF-8, spaces only, indent is a multiple of 2
- full-line ``#`` comments and blank lines
- ``key: value`` scalars (unquoted strings, double-quoted strings, integers)
- one nested block under a key, used for ``entries:``
- list items are flat mappings (``- key: value`` plus indented keys)

Flow collections, anchors, block scalars, and tabs are rejected.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SKILL_FILE_CAP_BYTES = 8192
ROOT_KEYS = (
    "schema_version",
    "upstream_repository",
    "upstream_commit",
    "fork_repository",
    "entries",
)
ENTRY_KEYS = ("id", "kind", "role", "plugin", "path")
KINDS = ("agent", "skill")
SLUG = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
COMMIT = re.compile(r"[0-9a-f]{40}")
AGENT_PATH = re.compile(r"plugins/[^/]+/agents/[^/]+\.md")
SKILL_PATH = re.compile(r"plugins/[^/]+/skills/[^/]+/SKILL\.md")
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


class ManifestError(Exception):
    """A parse error with a 1-based line number."""

    def __init__(self, line: int, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(message)


def parse_manifest(text: str) -> dict:
    """Parse the supported YAML subset. Return the root mapping."""
    lines = _prepare(text)
    if not lines:
        raise ManifestError(1, "manifest is empty. fix: write the selection mapping")
    data, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        number = lines[index][0]
        raise ManifestError(number, "extra content after the manifest. fix: remove it")
    if not isinstance(data, dict):
        raise ManifestError(1, "manifest root must be a mapping. fix: start with key: value lines")
    return data


def validate_data(data: dict, root: Path) -> list[str]:
    """Return semantic errors. An empty list means the manifest is valid."""
    errors: list[str] = []
    unknown = sorted(set(data) - set(ROOT_KEYS))
    if unknown:
        errors.append(
            f"unknown root keys {unknown}. fix: keep only {list(ROOT_KEYS)}"
        )
    missing = [key for key in ROOT_KEYS if key not in data]
    if missing:
        errors.append(f"missing root keys {missing}. fix: add them to the manifest")
        return errors

    if data["schema_version"] != SCHEMA_VERSION:
        errors.append(
            "schema_version must be integer 1. fix: set schema_version: 1"
        )
    for field in ("upstream_repository", "fork_repository"):
        value = data[field]
        if not isinstance(value, str) or not value.strip() or "/" not in value:
            errors.append(
                f"{field} must be an owner/name string. fix: set {field}: owner/name"
            )
    commit = data["upstream_commit"]
    if not isinstance(commit, str) or COMMIT.fullmatch(commit) is None:
        errors.append(
            "upstream_commit must be 40 lowercase hex characters. "
            "fix: set the studied upstream commit"
        )

    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list. fix: add at least one path")
        return errors

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    root_real = root.resolve()
    for entry in entries:
        errors.extend(_validate_entry(entry, root_real, seen_ids, seen_paths))
    return errors


def validate_file(manifest: Path, root: Path) -> list[str]:
    """Parse ``manifest`` and validate it against ``root``."""
    if not manifest.is_file():
        return [f"{manifest}: file does not exist. fix: create the selection manifest"]
    try:
        text = manifest.read_text(encoding="utf-8")
    except UnicodeError as exc:
        return [f"{manifest}: not UTF-8 ({exc}). fix: save the manifest as UTF-8"]
    try:
        data = parse_manifest(text)
    except ManifestError as exc:
        return [f"{manifest}:{exc.line}: {exc.message}"]
    return [f"{manifest}: {error}" for error in validate_data(data, root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate egregore/selection.yaml")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: working directory)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="manifest path (default: <root>/egregore/selection.yaml)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest if args.manifest is not None else root / "egregore" / "selection.yaml"
    if not manifest.is_absolute():
        manifest = root / manifest
    errors = validate_file(manifest, root)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    count = len(parse_manifest(manifest.read_text(encoding="utf-8"))["entries"])
    print(f"OK: {count} selection entries in {manifest}")
    return 0


def _validate_entry(
    entry: object,
    root: Path,
    seen_ids: set[str],
    seen_paths: set[str],
) -> list[str]:
    if not isinstance(entry, dict):
        return ["each entry must be a mapping. fix: use - id: ... under entries"]
    label = entry.get("id", "<missing id>")
    errors: list[str] = []
    unknown = sorted(set(entry) - set(ENTRY_KEYS))
    if unknown:
        errors.append(f"entry {label}: unknown keys {unknown}. fix: keep only {list(ENTRY_KEYS)}")
    missing = [key for key in ENTRY_KEYS if key not in entry]
    if missing:
        errors.append(f"entry {label}: missing keys {missing}. fix: add them")
        return errors

    entry_id = entry["id"]
    if not isinstance(entry_id, str) or SLUG.fullmatch(entry_id) is None:
        errors.append(
            f"entry {label}: id must be a lowercase slug. fix: use words separated by hyphens"
        )
    elif entry_id in seen_ids:
        errors.append(f"entry {entry_id}: duplicate id. fix: keep one entry per id")
    else:
        seen_ids.add(entry_id)

    kind = entry["kind"]
    if kind not in KINDS:
        errors.append(
            f"entry {entry_id}: kind must be agent or skill. fix: set kind: agent or kind: skill"
        )
    role = entry["role"]
    if not isinstance(role, str) or SLUG.fullmatch(role) is None:
        errors.append(f"entry {entry_id}: role must be a lowercase slug. fix: rename role")
    plugin = entry["plugin"]
    if not isinstance(plugin, str) or SLUG.fullmatch(plugin) is None:
        errors.append(f"entry {entry_id}: plugin must be a lowercase slug. fix: set the plugin name")

    path = entry["path"]
    if not isinstance(path, str):
        errors.append(f"entry {entry_id}: path must be a string. fix: quote or write the path")
        return errors
    path_error = _path_shape(entry_id, kind if isinstance(kind, str) else "", path)
    if path_error:
        errors.append(path_error)
        return errors
    if isinstance(plugin, str) and path.split("/")[1] != plugin:
        errors.append(
            f"entry {entry_id}: plugin {plugin!r} does not match {path}. "
            "fix: set plugin to the directory under plugins/"
        )
        return errors
    if path in seen_paths:
        errors.append(f"entry {entry_id}: duplicate path {path}. fix: reference each file once")
    else:
        seen_paths.add(path)

    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        errors.append(
            f"entry {entry_id}: path escapes the repository: {path}. "
            "fix: point at a file under plugins/"
        )
        return errors
    if not candidate.is_file():
        errors.append(
            f"entry {entry_id}: path does not exist: {path}. fix: correct the path or restore the file"
        )
        return errors
    if kind == "skill":
        size = candidate.stat().st_size
        if size > SKILL_FILE_CAP_BYTES:
            errors.append(
                f"entry {entry_id}: skill file is {size} bytes, over the {SKILL_FILE_CAP_BYTES} "
                "byte Codex cap. fix: choose a skill whose whole file fits, or drop it from the starter set"
            )
    return errors


def _path_shape(entry_id: str, kind: str, path: str) -> str | None:
    if path.startswith("/") or "\\" in path or ":" in path:
        return (
            f"entry {entry_id}: path must be a relative posix path. "
            "fix: use plugins/<plugin>/..."
        )
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return (
            f"entry {entry_id}: path must not contain empty, '.', or '..' segments. "
            "fix: write a direct plugins/ path"
        )
    pattern = AGENT_PATH if kind == "agent" else SKILL_PATH if kind == "skill" else None
    if pattern is not None and pattern.fullmatch(path) is None:
        expected = (
            "plugins/<plugin>/agents/<name>.md"
            if kind == "agent"
            else "plugins/<plugin>/skills/<name>/SKILL.md"
        )
        return f"entry {entry_id}: kind {kind} requires {expected}. fix: correct path"
    return None


def _prepare(text: str) -> list[tuple[int, int, str]]:
    lines: list[tuple[int, int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        raw = raw.rstrip("\r")
        if "\t" in raw:
            raise ManifestError(number, "tabs are not allowed. fix: indent with spaces")
        if not raw.strip() or raw.lstrip(" ").startswith("#"):
            continue
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if indent % 2 != 0:
            raise ManifestError(
                number,
                f"indent is {indent}, not a multiple of 2. fix: use 2 spaces per level",
            )
        lines.append((number, indent, stripped))
    return lines


def _parse_block(
    lines: list[tuple[int, int, str]], index: int, indent: int
) -> tuple[dict | list, int]:
    if index >= len(lines):
        raise ManifestError(1, "expected a block. fix: add the nested lines")
    number, found, text = lines[index]
    if found != indent:
        raise ManifestError(
            number,
            f"expected indent {indent}, found {found}. fix: align this block",
        )
    if text.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(
    lines: list[tuple[int, int, str]], index: int, indent: int
) -> tuple[dict, int]:
    data: dict = {}
    while index < len(lines):
        number, found, text = lines[index]
        if found != indent or text.startswith("- "):
            break
        key, raw = _split_kv(number, text)
        if key in data:
            raise ManifestError(number, f"duplicate key {key}. fix: keep one {key}")
        if raw is None:
            index += 1
            expected = indent + 2
            if index >= len(lines) or lines[index][1] != expected:
                raise ManifestError(
                    number,
                    f"key {key} needs a nested block indented {expected} spaces. "
                    "fix: indent the following lines",
                )
            child, index = _parse_block(lines, index, expected)
            data[key] = child
        else:
            data[key] = _scalar(number, raw)
            index += 1
    if not data:
        number = lines[index][0] if index < len(lines) else 1
        raise ManifestError(number, "expected a mapping. fix: add key: value lines")
    return data, index


def _parse_list(
    lines: list[tuple[int, int, str]], index: int, indent: int
) -> tuple[list, int]:
    items: list[dict] = []
    while index < len(lines):
        number, found, text = lines[index]
        if found != indent or not text.startswith("- "):
            break
        key, raw = _split_kv(number, text[2:])
        if raw is None:
            raise ManifestError(
                number,
                "list items must be flat mappings. fix: put a scalar on the dash line",
            )
        item = {key: _scalar(number, raw)}
        index += 1
        while index < len(lines):
            child_number, child_indent, child_text = lines[index]
            if child_indent != indent + 2 or child_text.startswith("- "):
                break
            child_key, child_raw = _split_kv(child_number, child_text)
            if child_key in item:
                raise ManifestError(
                    child_number,
                    f"duplicate key {child_key}. fix: keep one {child_key}",
                )
            if child_raw is None:
                raise ManifestError(
                    child_number,
                    "nested list-item values are not supported. fix: use a scalar",
                )
            item[child_key] = _scalar(child_number, child_raw)
            index += 1
        items.append(item)
    if not items:
        number = lines[index][0] if index < len(lines) else 1
        raise ManifestError(number, "expected a list item. fix: start a line with - key: value")
    return items, index


def _split_kv(number: int, text: str) -> tuple[str, str | None]:
    if ":" not in text:
        raise ManifestError(number, f"expected key: value, found {text!r}. fix: add a colon")
    key, rest = text.split(":", 1)
    if KEY.fullmatch(key) is None:
        raise ManifestError(
            number,
            f"invalid key {key!r}. fix: use letters, digits, '_' , or '-'",
        )
    if rest == "":
        return key, None
    if not rest.startswith(" "):
        raise ManifestError(number, "a space is required after ':'. fix: write key: value")
    value = rest[1:].rstrip()
    if value == "":
        raise ManifestError(number, f"key {key} has an empty value. fix: write a scalar or nest a block")
    return key, value


def _scalar(number: int, raw: str) -> str | int:
    if raw[0] in "[{\n&*!|>":
        raise ManifestError(
            number,
            f"unsupported YAML value {raw!r}. fix: use a plain scalar",
        )
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            raise ManifestError(number, "unterminated double quote. fix: close the string")
        return _unquote(number, raw[1:-1])
    if raw.startswith("'"):
        raise ManifestError(number, "single quotes are not supported. fix: use a plain or double-quoted scalar")
    if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw):
        return int(raw)
    return raw


def _unquote(number: int, body: str) -> str:
    out: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            if char not in ('\\', '"'):
                raise ManifestError(number, rf"unsupported escape \{char}. fix: use \\ or \"")
            out.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    if escaped:
        raise ManifestError(number, "dangling backslash in string. fix: escape it as \\\\")
    return "".join(out)


if __name__ == "__main__":
    sys.exit(main())
