# Egregore integration

This directory is the fork-owned bridge between [wshobson/agents](https://github.com/wshobson/agents) and Egregore. Egregore is the MCP coordination server that will own tasks, orchestration, and permissions. This repository provides specialist roles, skills, and the configs that describe them.

The study used commit `0874a27b17a22e2b7c2e2bcd725768e0803cad06` (`docs(documentation-generation): avoid overwriting ADR README in toc example (#778)`, 2026-10-17). On 2026-10-27 that commit was `main` on both `wshobson/agents` and this fork, `AStrasler/agents`. Upstream content stays where it is. Files under `egregore/` only refer to it.

Specialist agents cannot talk to each other over MCP without client integration.

An agent file and a skill file are prompts. They are not MCP servers, they do not listen on a socket, and they do not call each other. `mcp_servers: true` in [`tools/adapters/capabilities.py`](../tools/adapters/capabilities.py) means the Cursor and Codex clients can attach an MCP server. It does not give `code-reviewer.md` a channel to `docs-architect.md`. Egregore can be that server only after a client loads one specialist prompt and calls Egregore itself. Putting both files in one checkout does not connect them.

## What is reusable

Shared source lives under `plugins/<name>/`. Each plugin has a `.claude-plugin/plugin.json` and any of three component types:

| Component | Path | Role for Egregore |
| --- | --- | --- |
| Agent | `plugins/<name>/agents/<agent>.md` | A specialist persona. Frontmatter carries `name`, `description`, and `model`. |
| Skill | `plugins/<name>/skills/<skill>/SKILL.md` | Modular instructions plus on-demand `references/`. This is the portable unit. |
| Command | `plugins/<name>/commands/<command>.md` | A client slash workflow. Useful later. Not part of the starter set, because a command is a client-run procedure and Egregore owns orchestration. |

Authors write the Claude Code Markdown format once. Adapters in [`tools/adapters/`](../tools/adapters/) rewrite it. [`capabilities.py`](../tools/adapters/capabilities.py) is the capability matrix those adapters consult. [`docs/harnesses.md`](../docs/harnesses.md) is the human-readable copy. The seven documented harnesses are Claude Code, Codex CLI, Cursor, OpenCode, Antigravity CLI, GitHub Copilot, and Pi. ChatGPT and Grokbot are not in that list.

Two adapters matter for the clients below.

- **Cursor** ([`tools/adapters/cursor.py`](../tools/adapters/cursor.py)) writes manifests only: `.cursor-plugin/marketplace.json`, `.cursor-plugin/plugins/<name>.json`, and curated `.cursor/rules/*.mdc`. It does not rewrite agent or skill bodies. Marketplace entries use `source: ./plugins/<name>`.
- **Codex** ([`tools/adapters/codex.py`](../tools/adapters/codex.py)) commits `.agents/plugins/marketplace.json` and `plugins/<name>/.codex-plugin/plugin.json` for plugins that have source skills. Those manifests point `skills` at `./skills/`. Agent TOML and rewritten skills under `.codex/` are generated and gitignored. Skill files over 8192 bytes are a hard error in [`tools/validate_generated.py`](../tools/validate_generated.py). Codex native install truncates a source skill at that cap.

Egregore should read the paths in [`selection.yaml`](selection.yaml) from a pinned checkout. It should not copy the bodies into its own tree. A copy would fork the prompt away from upstream and hide renames that the selection check is there to catch.

Egregore should not treat frontmatter as an enforcement layer.

- The two selected agents have no `tools:` field. In Codex, a missing `tools:` field becomes `sandbox_mode = "workspace-write"` ([`codex.py`](../tools/adapters/codex.py) maps that case to the permissive sandbox). The generated files confirm it: `comprehensive-review__code-reviewer.toml` and `documentation-generation__docs-architect.toml`.
- Cursor does not honor a per-agent `tools:` allowlist. [`capabilities.py`](../tools/adapters/capabilities.py) records `tool_allowlist_per_agent` as false for Cursor, and [`docs/harnesses.md`](../docs/harnesses.md) says the same.
- Permissions belong to Egregore and to the client sandbox around the run.

Egregore should also leave orchestrator plugins where they are. `agent-orchestration`, `agent-teams`, `full-stack-orchestration`, and `tdd-workflows` (`tdd-orchestrator`) assume the client coordinates several agents. That is the job Egregore is taking. `protect-mcp` is a different policy product and is not part of this starter set.

## Starter set

Five files, three roles. [`selection.yaml`](selection.yaml) references them by path.

| Id | Role | Kind | Path | Source bytes |
| --- | --- | --- | --- | --- |
| `code-reviewer` | code reviewer | agent | `plugins/comprehensive-review/agents/code-reviewer.md` | 8436 |
| `code-review-excellence` | code reviewer | skill | `plugins/developer-essentials/skills/code-review-excellence/SKILL.md` | 6804 |
| `python-testing-patterns` | test writer | skill | `plugins/python-development/skills/python-testing-patterns/SKILL.md` | 7282 |
| `docs-architect` | docs writer | agent | `plugins/documentation-generation/agents/docs-architect.md` | 3693 |
| `architecture-decision-records` | docs writer | skill | `plugins/documentation-generation/skills/architecture-decision-records/SKILL.md` | 5048 |

Byte counts are the whole source file at the studied commit. The three skills are under the 8192-byte Codex cap. The selection check fails if a selected skill grows past that cap.

Why this set is the small one:

- **Code reviewer.** The agent is the persona Cursor can load as a subagent (`model: opus`, frontmatter name `comprehensive-review-code-reviewer`). The skill is the Codex-native review guide (`Use when reviewing pull requests...`). `comprehensive-review` has no `skills/` tree, so the Codex marketplace omits it. The skill's plugin, `developer-essentials`, is in that marketplace.
- **Test writer.** `python-testing-patterns` is a leaf pytest skill and fits the cap. `plugins/javascript-typescript/skills/javascript-testing-patterns/SKILL.md` is 14629 bytes, so a native Codex load would truncate it. `plugins/unit-testing/agents/test-automator.md` is a broad automation persona, its plugin has no skills so Codex native install skips the plugin, and its body includes coordination with a TDD orchestrator. The skill is the starter. The agent can be added later as its own entry.
- **Docs writer.** `docs-architect` (`model: sonnet`, frontmatter name `documentation-generation-docs-architect`) is the long-form documentation persona. `architecture-decision-records` is the Codex-native slice of the same plugin: ADRs, not general manuals. The plugin's committed Codex manifest sets `"skills": "./skills/"`, so native install exposes the skill and does not load the agent. The agent still needs `make generate HARNESS=codex`, which writes gitignored `.codex/agents/documentation-generation__docs-architect.toml`.

A client integration that uses the set does four things:

1. Pin this repository at `upstream_commit` from the manifest, or at a later fork commit whose `python3 egregore/validate_selection.py` still passes.
2. Ask Egregore for a task. Egregore chooses one role and returns one manifest path.
3. The client loads that file as the specialist prompt for that task. Cursor can do this through the marketplace plugin that contains the file, or by reading the path. Codex loads the three skills from the native plugin manifests. Codex loads the two agents only from generated TOML.
4. The client calls Egregore for task state, the next assignment, and permission decisions. The specialist prompt does not get a tool that invokes another specialist.

ChatGPT and Grokbot have no loader in this repository. Pasting a file into a chat box is a person moving text. It is not client support, and it still does not create an MCP session between specialists.

## Compatibility matrix

Labels mean specific things. They are not synonyms.

- **Documented.** A claim in `docs/`, `ARCHITECTURE.md`, `AGENTS.md`, or `tools/adapters/capabilities.py` at the studied commit.
- **Observed.** A file or command output inspected in this checkout during the study.
- **Verified.** A command in this study exercised that behavior and the recorded result matched. Where the cell is structural, it says so. This study did not install the Cursor marketplace, did not run the `codex` binary, and did not open ChatGPT or Grokbot.

| Client | Documented | Observed | Verified |
| --- | --- | --- | --- |
| Cursor | Skills and subagents from marketplace source `./plugins/<name>` ([`docs/harnesses.md`](../docs/harnesses.md)). MCP attach is supported. Per-agent tool allowlists are not. `model: opus` and `model: sonnet` rewrite to `inherit`. Parallel subagents and a Task spawn tool are supported. | `.cursor-plugin/marketplace.json` has entries for `comprehensive-review`, `developer-essentials`, `python-development`, and `documentation-generation`, each with `source` `./plugins/<name>`. Per-plugin manifests under `.cursor-plugin/plugins/` have no component list. This checkout has no `.claude/` directory. The adapter comment in `cursor.py` still says Cursor discovers `.claude/skills` and `.claude/agents`. [`docs/round-trip-results.md`](../docs/round-trip-results.md) says the same. [`docs/harnesses.md`](../docs/harnesses.md) says Cursor reads `SKILL.md` and agent markdown from the plugin source. The files that exist for this set are under `plugins/`. | `make validate STRICT=1` passed and includes the committed Cursor marketplace. No Cursor plugin install. The round-trip doc lists Cursor as `n/a` because there is no CLI. |
| Codex CLI | Native marketplace for plugins that contain source skills. Agents are TOML from `make generate`. Skill cap is 8192 bytes. MCP attach is supported. `task_spawn` is false: delegation is naming an agent in prose. `opus` maps to `gpt-5.5`. `sonnet` maps to `gpt-5.4-mini`. | `.agents/plugins/marketplace.json` includes `developer-essentials`, `python-development`, and `documentation-generation`. It has no `comprehensive-review` entry and no `unit-testing` entry. The three included plugins have `.codex-plugin/plugin.json` with `"skills": "./skills/"`. `comprehensive-review` has no `.codex-plugin/` directory. After `make generate-all`, these gitignored files existed and the skills were still under the cap: `developer-essentials__code-review-excellence/SKILL.md` 6826 bytes, `python-development__python-testing-patterns/SKILL.md` 7302 bytes, `documentation-generation__architecture-decision-records/SKILL.md` 5074 bytes, `comprehensive-review__code-reviewer.toml` (`model` `gpt-5.5`, `sandbox_mode` `workspace-write`), `documentation-generation__docs-architect.toml` (`model` `gpt-5.4-mini`, `sandbox_mode` `workspace-write`). | `make generate-all` exited 0. `make validate STRICT=1` then exited 0. Round-trip pytest that had skipped for a missing `.codex/` tree passed after generation (see the study record). The `codex` binary was not on `PATH`. `codex doctor` and an interactive skill load were not run. |
| ChatGPT | This repository documents no ChatGPT harness, adapter, manifest, install command, or test. Codex CLI is the documented OpenAI client, and it is a different program. | No ChatGPT file, branch, or test name in the tree. | Not run. |
| Grokbot | This repository documents no Grokbot harness, adapter, manifest, install command, or test. | No Grokbot file, branch, or test name in the tree. | Not run. |

The same boundary, one row per capability:

| Capability | Cursor | Codex | ChatGPT | Grokbot |
| --- | --- | --- | --- | --- |
| Load a selected skill | Documented and observed via marketplace `source`. Not verified in a Cursor session. | Documented, observed in the native manifest and the generated skill, verified structurally. | Absent | Absent |
| Load a selected agent | Documented. Source agent files observed. No generated Cursor agent exists to inspect, because the adapter does not emit one. Not verified in a Cursor session. | Documented as generated TOML. Observed after `make generate-all`. Native marketplace does not list `comprehensive-review`. Not verified with the Codex binary. | Absent | Absent |
| Attach an MCP server | Documented (`mcp_servers: true`). Not verified here. | Documented (`mcp_servers: true`). Not verified here. | Absent from this repo | Absent from this repo |
| Specialist talks to another specialist over MCP | Absent. A documented Task tool is still the client spawning work. | Absent. Documented delegation is prose, and `task_spawn` is false. | Absent | Absent |

## Fork maintenance

Origin stays `https://github.com/AStrasler/agents.git`. Upstream is `https://github.com/wshobson/agents.git`. Add it once:

```bash
git remote add upstream https://github.com/wshobson/agents.git
```

Sync cadence: once a week, and again before any edit to `egregore/selection.yaml`. At study time the two `main` branches matched. The latest upstream commit on that day was the 2026-10-17 commit above, so a week is enough to notice movement without turning every upstream commit into a fork merge.

Procedure:

```bash
git fetch upstream
git checkout main
git merge upstream/main
python3 egregore/validate_selection.py
python3 egregore/test_validate_selection.py
```

Merge `upstream/main` into the fork `main`. Do not rebase published `main`, and do not force-push it. Open pull requests against `AStrasler/agents` `main`. Do not open them against `wshobson/agents`. Do not commit generated trees (`.codex/`, `.opencode/`, `.copilot/`, `.antigravity/`, `.pi/`).

Conflict policy:

- `egregore/` is the only fork-owned tree. A conflict there is resolved by keeping the fork's integration text. If the conflict exists because upstream renamed a file named in `selection.yaml`, update the path and re-run the selection check. Do not paste upstream prompt bodies into `egregore/`.
- A conflict outside `egregore/` means the fork changed an upstream file. Restore that path from `upstream/main`. Do not rewrite upstream content, `LICENSE`, attribution, or third-party notices to keep a fork edit.
- If upstream later adds its own `egregore/` directory, stop and reconcile by hand. Do not delete upstream files to win the merge.
- After the merge, the selection check is the gate. A renamed or removed specialist fails `python3 egregore/validate_selection.py` until the manifest is updated.

## Selection check

`validate_selection.py` and `test_validate_selection.py` use only the standard library. They are not part of `make test`. Run them from the repository root:

```bash
python3 egregore/validate_selection.py
python3 egregore/test_validate_selection.py
```

The script accepts the YAML subset in its module docstring: two-space indent, scalars, one nested `entries` list of flat mappings. It rejects tabs, flow collections, unknown keys, duplicate ids, duplicate paths, absolute paths, `..` segments, and symlinks that resolve outside the repository. `kind: agent` must match `plugins/<plugin>/agents/<name>.md`. `kind: skill` must match `plugins/<plugin>/skills/<name>/SKILL.md`. The `plugin` field must match the directory under `plugins/`. Each skill file must be at most 8192 bytes. `upstream_commit` must be 40 lowercase hex characters. The script does not call `git`, and it does not require that commit to equal `HEAD` after this fork adds its own commits.

## Study record

Commands were run from a clean checkout of `0874a27b17a22e2b7c2e2bcd725768e0803cad06`. `uv` 0.13.6 installed CPython 3.14.10 because `plugins/plugin-eval/.python-version` says `3.14`. The CI generate job sets `UV_PYTHON=3.12`. This study used 3.14.10. `make generate-all` still left the tracked tree clean.

| Command | Result |
| --- | --- |
| `make validate STRICT=1` before generation | Exit 0. `OK: no issues across 6 harness(es).` `.codex/` was absent, and `validate_codex` returns immediately in that case, so this pass did not inspect generated Codex, OpenCode, Copilot, Antigravity, or Pi trees. The committed Cursor marketplace was checked. |
| `make garden` | Exit 0. `OK: garden is clean (9 check(s) ran).` |
| `make test` before generation | Exit 0. `710 passed, 28 skipped in 4.58s`. Every skip is in `tools/tests/test_round_trip.py` and asks for a generated harness tree. |
| `make lint` | Exit 0. `ruff check` passed, `ruff format --check` reported 46 files already formatted, `ty check` passed. |
| `make generate-all` | Exit 0. `git status --porcelain` was empty. Tracked registries did not drift. |
| `make validate STRICT=1` after generation | Exit 0. `OK: no issues across 6 harness(es).` |
| `make test` after generation | Exit 0. `738 passed in 4.57s`. The 28 round-trip skips ran and passed. |

`make smoke-test` was not run. That target generates trees and then runs `tools/tests/test_cli_smoke.py`, which invokes real CLIs, including `gh skill install` and `npx skills add`. This integration does not install plugins. OpenCode, Antigravity, Pi, and Codex were not installed, so a live CLI round-trip was not verified here. The historical results in [`docs/round-trip-results.md`](../docs/round-trip-results.md) stay historical.

### Findings

1. Specialist prompts have no MCP peer channel. Client integration has to load one prompt and call Egregore. The capability flag only records that Cursor and Codex can attach a server.
2. Codex native install and Codex agent TOML are different routes. The three skills are on the native route. The two agents are on the generate route. `comprehensive-review` is absent from `.agents/plugins/marketplace.json`.
3. The selected source skills fit the 8192-byte whole-file cap (6804, 7282, and 5048). Their generated copies also fit (6826, 7302, and 5074).
4. Neither selected agent sets `tools:`. Generated Codex sandbox mode is `workspace-write`. Egregore cannot read a permission policy out of these files.
5. Cursor's own docs in this repo disagree about discovery. The marketplace source path is `./plugins/<name>`, and that tree is what this checkout contains. Adapter comments and the Cursor round-trip recipe still say `.claude/skills`. This study did not install the marketplace, so which of those a live Cursor session scans was not verified.
6. Directory counts at this commit: 92 plugin directories, 202 agent files, 185 `SKILL.md` files, 105 command files. `AGENTS.md` matches those counts. The description string in `.claude-plugin/marketplace.json` still says "181 local skills". `make garden` checks counts in `README.md` and `AGENTS.md`, so that stale sentence did not fail the garden run.
7. [`CONTRIBUTING.md`](../CONTRIBUTING.md) says `main` carries ten `SKILL_OVER_CODEX_CAP` warnings. This run printed a clean garden. That check warns only when a skill body exceeds the cap and the skill has no `references/` directory.
8. A fresh `make validate STRICT=1` can pass while generated trees are missing. The pass that inspected those trees is the one after `make generate-all`.
