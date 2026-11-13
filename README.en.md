**English** | [简体中文](README.md)

<div align="center">

<p><img src="docs/assets/hero-hongzhao.gif" alt="hongzhao hero: a crane lifts off a snowy field, leaving prints behind" width="360"></p>
<sub>Named after 雪泥鸿爪 — the goose lands on snow, leaves its prints, and flies on.</sub>

# hongzhao

**A file-based, human-gated memory ledger for AI coding agents — deterministic, zero lock-in.**

[Getting started](docs/en/getting-started.md) · [Install](docs/en/INSTALL.md) · [Design](docs/en/design.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

[![PyPI](https://img.shields.io/pypi/v/hongzhao?label=PyPI)](https://pypi.org/project/hongzhao/)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab)](https://pypi.org/project/hongzhao/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-8a8a8a)](#support-matrix)
[![License](https://img.shields.io/badge/license-Apache--2.0-3da639)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-中文%C2%B7English-7016d5)](docs/)

</div>

Agents take notes constantly; most of those notes rot in chat logs. hongzhao gives
your agent a small set of plain-text ledgers — claims, project contracts, knowledge
entries — with deterministic validation and compilation. Nothing enters an agent's
context until you (or a rule you wrote) say so.

- **Plain files, no lock-in.** Markdown + YAML under one root. No server, no database, no cloud.
- **Two gates.** Raw notes are candidates; `compile` turns reviewed candidates into effective views. Candidates never leak into context.
- **Deterministic core.** Validation, compilation and rendering are pure scripts; only semantic judgment (what is a fact, what supersedes what) belongs to the agent.

> **Status: pre-release (v0.1).** Interfaces may change before `v0.1.0`.

## Install with your AI agent (one line)

Tell your coding agent (Claude Code, Codex CLI, ZCode, pi, dsh, OpenCode, ...):

```text
Read https://github.com/cmeng-CM/hongzhao/blob/main/docs/en/INSTALL.md and install hongzhao for me. My client is claude_code.
```

It will follow the [agent install protocol](docs/en/INSTALL.md#agent-install-protocol)
and report a pass/fail table. Prefer typing yourself? [Manual install](docs/en/INSTALL.md#manual-install)
is three commands.

## Support matrix

| | Status |
| --- | --- |
| macOS / Linux | Supported (Python 3.9+; CI-tested on 3.12/3.13) |
| Windows 10+ native | Supported (Python 3.9–3.13; skills link via NTFS junctions, no developer mode needed; except network/synced drives such as OneDrive (junctions unsupported there)) |
| Python | 3.9+ (CI-tested on 3.12/3.13; single runtime dependency: PyYAML) |
| Preset clients | Claude Code, Codex CLI, ZCode, pi, dsh (DeepSeek Harness), OpenCode (more via custom config) |
| Install | `pip` / `uv` / `pipx` |

## With / without

| Concern | Without hongzhao | With hongzhao |
| --- | --- | --- |
| Agent notes | Scattered across chat logs, gone on close | Versioned raw records with schema and trace |
| What the agent "knows" | Whatever is pasted into the prompt | Compiled effective views, routed by task |
| Conflicting facts | Last message wins | Explicit relations (supersedes / conflicts) resolved at compile time |
| Onboarding a new agent session | Re-explain everything | One bootstrap block injected into the client file |
| Client-side auto-memory | Each client hoards its own copy, never trimmed | `collect` absorbs facts into the ledger and deletes the source (human gate + hash-guarded delete) |
| Leaving the tool | — | Delete the managed block; your files remain plain markdown |

## 60-second quickstart

```bash
pip install hongzhao            # or: uv tool install hongzhao
hongzhao init ~/my-memory --example
hongzhao --root ~/my-memory compile
hongzhao --root ~/my-memory validate
```

You now have a green demo kit: raw notes, a compiled index, and a rendered
bootstrap. Explore `~/my-memory/compiled/` — every view is plain markdown.

Daily loop:

```bash
hongzhao --root ~/my-memory validate     # schema + containment checks
hongzhao --root ~/my-memory compile      # rebuild derived views
hongzhao --root ~/my-memory doctor       # client / blocks / output health
```

If the kit is a standalone git repo, every `compile` auto-commits it
(`git.auto_commit` defaults to on; set it to `false` to opt out) — memory is
plain files, git is the backup.

## Agent installation block

Paste this into your agent client's instruction file (or let `bridge-install`
manage the block for you — see [docs/en/clients.md](docs/en/clients.md)):

```text
# hongzhao memory routing
memory_root: ~/my-memory
Read compiled/bootstrap.md first; route tasks via compiled/effective-memory/index.md.
Never read raw/ except for evidence tracing. Run `hongzhao --root ~/my-memory compile`
after writing records; treat compile errors as stop signals.
```

## How it works

```
raw/ (claims, dated truth)        ──compile──▶  compiled/ (effective views)
registry/ + project contracts     ──compile──▶  render/   (bootstrap, client blocks)
knowledge registry                ──compile──▶  knowledge map
```

Five explicit relations between claims (supersedes, covers, derives, conflicts,
resolves) replace "newest wins". See [docs/en/claim-schema.md](docs/en/claim-schema.md)
and the diagrams in [docs/en/design.md](docs/en/design.md).

## Non-goals

- No MCP server, no vector search, no RAG, no auto-extraction, no web UI.
- No team sharing / multi-machine sync (single-writer by design).
- Kits on network/synced drives (e.g. OneDrive) are unsupported — junctions cannot be created there.
- No background daemons — every command is explicit, every write is atomic.

## Why-not

Approaches we deliberately did **not** take (and what to use instead):

- **Vector DB / embeddings:** file paths and titles already route a coding agent well; retrieval quality was not the bottleneck, review discipline was.
- **Auto-summarization on every turn:** unreviewed summaries are how memory rots; hongzhao makes candidates explicit and gates them.
- **A server / API:** a memory you cannot `grep`, diff, and back up with git is not your memory.
- **An embedded database:** merge conflicts and plain-text portability beat query power at this data scale.

---

Full documentation: [docs/](docs/) (中文) · [docs/en/](docs/en/) (English). Security
model: [SECURITY.md](SECURITY.md). Contributing (DCO required):
[CONTRIBUTING.md](CONTRIBUTING.md).

License: Apache-2.0 — see [LICENSE](LICENSE).
