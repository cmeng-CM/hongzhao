# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this is

hongzhao is a file-based, human-gated memory ledger for AI coding agents:
Markdown+YAML `raw/` records are the single source of truth, a deterministic
engine (zero LLM calls, single runtime dependency PyYAML) compiles them into
derived views, and nothing becomes "effective" until a human-gated review
flips it. See `README.md` and `docs/design.md` for the full picture.

## Ground rules

- **The engine stays deterministic.** No LLM calls, no network, no new runtime
  dependencies inside `src/hongzhao/`. Semantic judgment belongs to the
  shipped skills (`src/hongzhao/skills/`), never to the engine.
- **Rendered products are derived state.** `compiled/` and `render/` are fully
  rebuildable; never hand-edit them in a memory kit. Templates and their
  frontmatter key sets are frozen — English output, keys unchanged.
- **The four shipped skills are Chinese by design** (CLI and docs are
  English). Don't translate them.
- **Privacy gate before anything public:** `scripts/check_clean.py` scans
  against an external wordlist (never committed). Real paths, names, and
  emails must not enter the repo — configure local-only hooks via environment
  variables instead of hardcoding.

## Build, test, release

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest                      # full suite (unit + contracts)
.venv/bin/python -m pytest tests/unit/test_engine_parity.py   # needs HONGZHAO_OLD_ENGINE env (skips otherwise)
```

- Tests: unit tests in `tests/unit/`, contract tests (J1–J6 registry
  lifecycle, 16-row state matrix, fault injection) in `tests/contracts/`.
- Releases are tag-driven: pushing `v*` runs `.github/workflows/release.yml`
  (build → smoke → Trusted Publishing to PyPI). Never publish manually.
- Keep `CHANGELOG.md` updated for user-visible changes.

## Conventions

- Sign-off your commits (DCO): `git commit -s`.
- Comments in this repo: Chinese for design-rationale comments, English for
  user-visible strings (CLI output, docs, rendered products).
- Minimal diffs; match existing style. Containment and registry invariants
  are contract-tested — if your change touches adjudication (J1–J6), the
  contract matrix must be extended, not relaxed.
