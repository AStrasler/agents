#!/usr/bin/env python3
"""Tests for egregore/validate_selection.py. Standard library only."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_selection

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve().parent / "validate_selection.py"
COMMIT = "0874a27b17a22e2b7c2e2bcd725768e0803cad06"
STARTER_IDS = (
    "code-reviewer",
    "code-review-excellence",
    "python-testing-patterns",
    "docs-architect",
    "architecture-decision-records",
)


def _manifest(entries: str, **fields: str) -> str:
    header = {
        "schema_version": "1",
        "upstream_repository": "wshobson/agents",
        "upstream_commit": COMMIT,
        "fork_repository": "AStrasler/agents",
    }
    header.update(fields)
    lines = [f"{key}: {value}" for key, value in header.items()]
    lines.append("entries:")
    body = textwrap.dedent(entries).strip("\n")
    lines.extend(f"  {line}" if line else "" for line in body.splitlines())
    return "\n".join(lines) + "\n"


AGENT_ENTRY = """
  - id: code-reviewer
    kind: agent
    role: code-reviewer
    plugin: sample-plugin
    path: plugins/sample-plugin/agents/reviewer.md
"""


class SelectionValidationTest(unittest.TestCase):
    def test_repository_manifest_and_starter_contract(self) -> None:
        manifest = ROOT / "egregore" / "selection.yaml"
        self.assertEqual(validate_selection.validate_file(manifest, ROOT), [])
        data = validate_selection.parse_manifest(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["upstream_repository"], "wshobson/agents")
        self.assertEqual(data["fork_repository"], "AStrasler/agents")
        self.assertEqual(data["upstream_commit"], COMMIT)
        self.assertEqual(tuple(entry["id"] for entry in data["entries"]), STARTER_IDS)
        self.assertEqual(
            {entry["role"] for entry in data["entries"]},
            {"code-reviewer", "test-writer", "docs-writer"},
        )

    def test_cli_accepts_repository_manifest(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK: 5 selection entries", proc.stdout)

    def test_missing_path_is_an_error(self) -> None:
        errors = self._errors(_manifest(AGENT_ENTRY), {})
        self.assertTrue(any("does not exist" in error for error in errors), errors)

    def test_present_agent_passes(self) -> None:
        errors = self._errors(
            _manifest(AGENT_ENTRY),
            {"plugins/sample-plugin/agents/reviewer.md": "role\n"},
        )
        self.assertEqual(errors, [])

    def test_duplicate_id_and_path(self) -> None:
        doubled = AGENT_ENTRY + AGENT_ENTRY.replace("code-reviewer", "code-reviewer", 1)
        errors = self._errors(
            _manifest(doubled),
            {"plugins/sample-plugin/agents/reviewer.md": "role\n"},
        )
        self.assertTrue(any("duplicate id" in error for error in errors), errors)
        self.assertTrue(any("duplicate path" in error for error in errors), errors)

    def test_path_escape_and_absolute_path(self) -> None:
        outside = AGENT_ENTRY.replace(
            "path: plugins/sample-plugin/agents/reviewer.md",
            "path: plugins/sample-plugin/agents/../../outside.md",
        )
        errors = self._errors(_manifest(outside), {})
        self.assertTrue(any("'.' , or '..'" in error or ".." in error for error in errors), errors)

        absolute = AGENT_ENTRY.replace(
            "path: plugins/sample-plugin/agents/reviewer.md",
            "path: /tmp/reviewer.md",
        )
        errors = self._errors(_manifest(absolute), {})
        self.assertTrue(any("relative posix path" in error for error in errors), errors)

    def test_symlink_cannot_leave_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / f"outside-{root.name}.md"
            outside.write_text("secret\n", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)
            link_parent = root / "plugins" / "sample-plugin" / "agents"
            link_parent.mkdir(parents=True)
            link = link_parent / "reviewer.md"
            link.symlink_to(outside)
            manifest = root / "egregore" / "selection.yaml"
            manifest.parent.mkdir()
            manifest.write_text(_manifest(AGENT_ENTRY), encoding="utf-8")
            errors = validate_selection.validate_file(manifest, root)
        self.assertTrue(any("escapes the repository" in error for error in errors), errors)

    def test_plugin_mismatch_and_kind_mismatch(self) -> None:
        mismatch = AGENT_ENTRY.replace("plugin: sample-plugin", "plugin: other-plugin")
        errors = self._errors(
            _manifest(mismatch),
            {"plugins/sample-plugin/agents/reviewer.md": "role\n"},
        )
        self.assertTrue(any("does not match" in error for error in errors), errors)

        skill_path = AGENT_ENTRY.replace(
            "path: plugins/sample-plugin/agents/reviewer.md",
            "path: plugins/sample-plugin/skills/reviewer/SKILL.md",
        )
        errors = self._errors(
            _manifest(skill_path),
            {"plugins/sample-plugin/skills/reviewer/SKILL.md": "x\n"},
        )
        self.assertTrue(any("kind agent requires" in error for error in errors), errors)

    def test_skill_cap_boundary(self) -> None:
        entry = """
          - id: sample-skill
            kind: skill
            role: test-writer
            plugin: sample-plugin
            path: plugins/sample-plugin/skills/sample-skill/SKILL.md
        """
        path = "plugins/sample-plugin/skills/sample-skill/SKILL.md"
        self.assertEqual(self._errors(_manifest(entry), {path: "x" * 8192}), [])
        errors = self._errors(_manifest(entry), {path: "x" * 8193})
        self.assertTrue(any("8192" in error for error in errors), errors)

    def test_rejects_bad_shape(self) -> None:
        cases = [
            "schema_version: 1\nentries: [\n",
            _manifest(AGENT_ENTRY).replace("schema_version: 1", "schema_version: 2"),
            _manifest(AGENT_ENTRY).replace("entries:\n", "entries:\n", 1) + "  - id: only\n",
            "schema_version: 1\nschema_version: 1\n",
            _manifest("  - id: code-reviewer\n    kind:\n      nested: no\n"),
        ]
        for text in cases:
            with self.subTest(text=text.splitlines()[0]):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    manifest = root / "selection.yaml"
                    manifest.write_text(text, encoding="utf-8")
                    errors = validate_selection.validate_file(manifest, root)
                self.assertNotEqual(errors, [], text)

    def test_cli_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "egregore" / "selection.yaml"
            manifest.parent.mkdir()
            manifest.write_text("schema_version: 2\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--manifest", str(manifest)],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error:", proc.stderr)

    def _errors(self, text: str, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            manifest = root / "egregore" / "selection.yaml"
            manifest.parent.mkdir()
            manifest.write_text(text, encoding="utf-8")
            return validate_selection.validate_file(manifest, root)


if __name__ == "__main__":
    unittest.main()
