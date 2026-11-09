# Changelog

Notable changes to hongzhao are documented here
([keep a changelog](https://keepachangelog.com/en/1.1.0/) format, starting
from `0.1.0`).

## [Unreleased]

## [0.3.0] — 2026-11-09

### Added

- Native Windows 10+ support (design `.delivery/2026-11-09-Windows-支持/`, two
  independent design reviews). Cross-platform lock (`msvcrt` on Windows),
  skill links via NTFS junctions (no admin/developer mode; network/synced
  drives such as OneDrive remain out of scope), green demo verified on
  windows CI (3.9–3.13), release smoke gains a Windows lane.

### Changed

- All engine and scaffold writes are LF-locked (`newline=""`): no-op on
  POSIX, ends CRLF output on Windows; compiled products are now byte-identical
  across platforms except environment fields (`memory_root`, `generated_at`).
- `write_atomic` gains a `newline` parameter; client instruction files keep
  their dominant line ending instead of being silently rewritten to LF
  (install / migrate-bridge / uninstall paths).
- `memory-index.yaml` record paths are always POSIX-style (`/` separators).
- Bridge reverse lookup (root discovery source 4) matches `@` paths only
  inside the managed block and now supports paths containing spaces.
- `os.replace` retries on transient `PermissionError` on Windows only;
  auto-commit compares the git toplevel with the root via `samefile`
  (works with mixed separators/case on Windows).
- Kits created by `init` now ship a `.gitattributes` with an `eol=lf` floor
  so Windows checkouts never trip the byte-compare in `skills-install`.

## [0.2.0] — 2026-11-09

### Added

- `git.auto_commit` config section: after a successful `compile`, hongzhao
  commits the whole kit automatically (on by default whenever the kit is a
  standalone git repo; opt out with `auto_commit: false`). Guards: the kit must
  be a standalone git repo (kits nested inside another repo are always
  refused); any git failure degrades to a warning and never blocks compile;
  commit messages are stable and greppable
  (`hongzhao compile v<ver> <ts> health=... effective=... pending=...`).

### Changed

- Compiles with unchanged content now reuse the previous `generated_at`, so
  no-op compiles are byte-identical (truly byte-reproducible); no-op compiles
  create no empty auto-commits. `last-compile-diff.md` still transitions once
  from the "first compile" narrative to steady state.

- Documentation is now Chinese-primary with an English mirror: `README.md` is
  the Chinese entry (language switch at the top), `README.en.md` is English,
  `docs/` holds the Chinese docs and diagrams, `docs/en/` the English ones.
  `README.zh-CN.md` was merged into `README.md` and removed.
- `docs/design.md` gains a design-philosophy section (problem statement, tradeoff
  table, success criteria) carried over from the author's original system
  design spec.

## [0.1.0] — 2026-11-06

First stable release. File-based, human-gated memory ledger for AI coding
agents: raw notes → explicit human review → deterministic compile → per-client
bootstrap. Zero LLM in the engine; PyYAML is the only runtime dependency.

Highlights of the 0.1.0 line (details under the rc entries below):

- Two-gate architecture: nothing enters effective memory until a human marks
  it reviewed; compile is byte-reproducible.
- Explicit relation algebra (`supersedes` / `covers` / `derived_from` /
  `conflicts_with` / `resolved_by`) with a deterministic adjudication table.
- Compile diff report (`compiled/last-compile-diff.md`) so the review gate can
  be audited, not just trusted.
- Four agent skills (write / compile / project context / closeout), two-path
  install (manual + agent protocol), three preset clients and custom ones.
- `hongzhao upgrade` with version-skew detection (`SKILL_STALE` /
  `BOOTSTRAP_STALE`) and a documented compatibility policy.
- Eval suite: 45 scenarios, fully mechanical scoring (84/84 runs passing),
  runnable as a CI gate.

## [0.1.0rc7] — 2026-11-05

### Added

- `hongzhao upgrade`: one command running the full upgrade sequence —
  `validate → skills-install all → compile → bridge-install all → doctor` —
  stopping at the first failing step (fix and re-run to resume).
- Version-skew visibility: the kit manifest records `_synced_with` and the
  rendered bootstrap records `engine_version`; `doctor` warns `SKILL_STALE` /
  `BOOTSTRAP_STALE` whenever the kit lags behind the installed engine —
  including the downgrade case (outputs from a newer engine are never silently
  misread).
- `docs/UPGRADE.md`: two-path upgrade doc (manual + agent protocol, same split
  as INSTALL.md) with a touches/never-touches table and the compatibility
  policy (sources never auto-rewritten; new validation rules land as warnings
  first; config renames keep aliases for two minor releases; 0.x/1.0 semver
  contract).

### Fixed

- Internal development decision IDs no longer leak into shipped artifacts
  (init-generated `.gitignore` comment, `templates/project-view.md` footer,
  two docs mentions).

## [0.1.0rc6] — 2026-11-03

### Fixed

- `project-register --dry-run` is now a true preview: the adjudication decision is
  computed read-only and nothing is written (previously the J6 path created the
  central contract and registry entry even in dry-run).
- `compile`/`validate` now report `CONTRACT_DUPLICATE` (degraded) when a project
  has both a root contract and a central contract, matching `doctor`; resolution
  still prefers the root contract. The three commands no longer disagree.
- Doctor's `LEGACY_MARKER` hint now shows the correct command
  (`hongzhao migrate-bridge`, which takes no arguments).
- `bridge-install`/`migrate-bridge` before the first compile now print an
  actionable `[OUTPUT_MISSING] ... run \`hongzhao compile\` first` instead of a
  bare fatal traceback.

### Added

- `created` dates in the future now produce a validation warning (not a block),
  so migration data with clock skew surfaces without breaking the gate.

## [0.1.0rc5] — 2026-11-02

### Fixed

- Registering a project without a project-root contract (J6: central contract
  under `projects/<key>/`) no longer makes the very next `compile`/`validate`
  fail with `CONTRACT_MISSING`. `load_contracts` now falls back to the central
  contract, matching the semantics `doctor` already used. Project-root
  contracts still take precedence (J1), and a genuinely missing contract
  (neither form) still reports `CONTRACT_MISSING`.

## [0.1.0rc4] — 2026-11-02

### Fixed

- No real machine paths in the repository: the engine-parity test now takes
  the legacy engine path from `HONGZHAO_OLD_ENGINE` (skips when unset); the
  contract test report was redacted. Repo-level privacy scan is now clean.
- `--json` help text no longer claims `validate`/`doctor` support (only
  `root` honors it).

### Added

- Repository-root `AGENTS.md` — contributor/agent entry point (ground rules,
  build/test/release, conventions).

## [0.1.0rc3] — 2026-11-02

### Changed

- The shipped `memory-compile` skill now includes a reconciliation step:
  after compiling, the agent reads `compiled/last-compile-diff.md` and reports
  the actual delta (newly effective / no longer effective / newly pending /
  newly rejected, counts, health transition), checking it against its own
  review intent. A mismatch must be fixed in raw and recompiled before
  claiming completion — the agent's summary becomes verifiable instead of
  self-reported.

## [0.1.0rc2] — 2026-11-02

### Added

- Compile diff report: every `compile` now writes
  `compiled/last-compile-diff.md` comparing the new state against the previous
  memory index — newly effective / no-longer-effective / newly pending /
  newly rejected records, a counts table, and the health transition. The
  second gate (review-at-compile) becomes checkable instead of trust-based.
  First compiles report "no baseline"; an unreadable baseline never blocks
  compilation.

## [0.1.0rc1] — 2026-11-02

First release candidate of the file-based, human-gated memory ledger for AI
coding agents.

### Added

- Root discovery from four sources (flag / env / config / cwd) with a fatal
  fallback (`hongzhao root`).
- `init` scaffolding: three-of-two client detection, `<root>/.gitignore`
  seeding, and a green `--example` scenario.
- `validate` / `compile`: field schema checks, memory/knowledge containment
  rules, deterministic English-rendered artifacts (index, bootstrap, project
  views, knowledge map).
- Client bridge: managed `<hongzhao-bootstrap>` blocks injected and refreshed
  in client bootstrap files (`bridge-install`, checked entry).
- `skills-install`: symlinks the four core skills (shipped in Chinese) into
  enabled clients; `--manifest-only` for change-set packaging.
- Contracts: flock-guarded registry, J1–J6 adjudication table, legacy-id
  aliases, `project-check` lookup order, and four fault-injection points for
  contract tests.
- `doctor` health checks with a `LEGACY_MARKER` whitelist and stable exit
  codes.
- Tooling: privacy gate (`scripts/check_clean.py`) and shadow-canary
  comparison scripts.

### Notes

- Pre-release candidate for the v0.1 beta cycle (macOS / Linux; Python 3.9+,
  CI-tested on 3.12/3.13; single runtime dependency PyYAML; no native Windows
  in this cycle).
- The source repository is private during the beta cycle and will be published
  with the v0.1.0 final release.

## [0.0.0] — Pre-history

- Repository bootstrap: governance baseline (Apache-2.0, DCO, CI scaffold,
  packaging skeleton). Pre-release, not published.
