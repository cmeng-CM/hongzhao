# Getting started

**English** | [简体中文](../getting-started.md)

From zero to a working memory kit in five minutes.

## Install

Requires Python 3.9+ (CI-tested on 3.12/3.13) on macOS / Linux / Windows 10+.
On Windows, skills link via NTFS junctions (no developer mode needed);
except network/synced drives such as OneDrive (junctions unsupported there).

```bash
pip install hongzhao          # or: uv tool install hongzhao / pipx install hongzhao
hongzhao --version
```

## Green demo (recommended first run)

```bash
hongzhao init ~/my-memory --example
hongzhao --root ~/my-memory compile
hongzhao --root ~/my-memory validate
```

`--example` seeds a tiny demo dataset (a profile claim, a correction, a
superseded note). After `compile`, inspect:

- `compiled/effective-memory/` — global / non-project / per-project effective views
- `compiled/effective-memory/index.md` — the routing index agents read first
- `compiled/current-state.md` — one-screen project status
- `compiled/last-compile-diff.md` — what this compile changed vs the previous one
- `render/bootstrap.md` — the block that gets injected into client files

`validate` exits 0 with no issues on the demo kit. That is the "green scenario".

## Daily loop

1. **Capture.** The agent writes a raw record under `raw/` (see
   [claim-schema.md](claim-schema.md)) — or you write one by hand.
2. **Gate.** You review the candidate (a raw record is *not* effective yet).
3. **Compile.** `hongzhao --root ~/my-memory compile` rebuilds all derived views.
4. **Check.** `hongzhao --root ~/my-memory validate && hongzhao --root ~/my-memory doctor`.

## Registering projects

A project contract is the single source of truth for one project's memory scope:

```bash
hongzhao --root ~/my-memory project-register ~/code/my-app \
  --purpose "Payment service" --current-state "Beta" \
  --next-action "Retry hardening" --key my-app
hongzhao --root ~/my-memory project-check ~/code/my-app
```

`project-register` writes a registry entry plus a central contract under
`projects/<key>/project-view.md` (J1–J6 lifecycle; see
[design.md](design.md)). `project-unregister` is dry-run by default.

## Collecting client memories (optional)

Client-side auto-memory (ZCode in v1) piling up? `collect` incrementally
absorbs the facts worth keeping into the ledger and removes the duplicates
on the client side:

```bash
hongzhao --root ~/my-memory collect --out manifest.yaml   # read-only pending manifest
# driven by the memory-collect skill: model extraction + your CHECKPOINT
hongzhao --root ~/my-memory collect --apply decision.yaml  # raw + ledger + conditional delete
```

- The three-state ledger `<root>/collect/<client>/ledger.yaml` records
  decided entries only: discards never resurface, changed content re-enters
  review, repeated collects produce zero duplicate candidates.
- Source deletion is content-hash guarded (modified files bounce back to
  review); `MEMORY.md` gets surgical line-level edits with original EOL
  preserved; raws land first and are auto-committed via `git.auto_commit`.
- The engine stays deterministic: "worth keeping?" and "duplicate of what?"
  are the skill's model-stage calls, with the human CHECKPOINT as the final
  gate.

## Registering knowledge

Long-lived reference material (docs, specs, postmortems) lives in your
knowledge root and is referenced by the knowledge registry:

```bash
hongzhao --root ~/my-memory knowledge-register docs/rust-async.md \
  --title "Rust async book" --topic rust \
  --summary "Async internals reference used for the runtime rewrite"
```

`path` is relative to the knowledge root (which defaults to the memory root
itself; set `knowledge_root` in config to keep reference material out of the
ledger). `--topic` may repeat. The target file must already exist.

## Clients (optional)

Enable a client to get a managed bootstrap block in its instruction file and
symlinked skills:

```bash
hongzhao --root ~/my-memory bridge-install
hongzhao --root ~/my-memory skills-install all
hongzhao --root ~/my-memory doctor
```

See [clients.md](clients.md) for the full lifecycle.

## Configuration

The kit is configured by `<root>/config.yaml`. Keys (unknown top-level keys are
rejected):

| Key | Meaning | Default |
| --- | --- | --- |
| `schema_version` | config schema, must be `2` | — |
| `paths` | 8 relative paths under the root (raw/compiled/registry/...) | conventional layout |
| `skills` | packaged skills to install | bundled set |
| `clients` | per-client settings (see below) | all disabled (`init --client` enables detected ones) |
| `output` | optional rendering options (`link_style`, `link_prefix`) | markdown links |
| `knowledge_root` | base directory for knowledge paths, relative to the root | `.` |
| `git` | auto-commit after compile (`auto_commit`); requires the kit itself to be a standalone git repo, nested repos are always refused, git failures degrade to a warning and never block compile | enabled (standalone repo) |

Per-client settings — exactly four keys (`enabled`, `bridge_path`, `skills_root`,
`mode`); unknown or missing keys are rejected with `CONFIG_INVALID`.

Two containment rules protect you: paths inside the memory tree must stay inside
the root; knowledge paths must stay inside `knowledge_root`. Both are enforced
on write, not on read.

## FAQ

**Q: Where does `hongzhao` look for my root?**
Four sources, in order: `--root`, then `$HONGZHAO_ROOT`, then the working
directory (walking up five levels looking for `config.yaml`), then the managed
block in a preset client instruction file (reverse lookup). A candidate that
fails validation is a hard error — never a silent fallback. `hongzhao root
--json` shows which one won.

**Q: What happens if I hand-edit a compiled file?**
Nothing breaks immediately, but the next `compile` overwrites it, and
`doctor`/canary comparisons will flag drift. Compiled and rendered files are
rebuildable views; edit `raw/` instead.

**Q: Can two agents write at the same time?**
Registry writes take an exclusive `flock` on `<root>/.hongzhao.lock` (10 s
timeout, `REGISTRY_BUSY` on contention). The kit is still single-writer by
design — concurrent registration is made safe, concurrent note-writing is not
encouraged.

**Q: How do I throw it away?**
`hongzhao --root ~/my-memory uninstall --yes` removes managed blocks and
skill symlinks (dry-run by default; `--delete-data` does not exist — delete the
root directory yourself).

**Q: Is my data sent anywhere?**
No. There is no networking code in the package at all (see
[SECURITY.md](../../SECURITY.md)).

**Q: Why is my health `review-needed`?**
A raw record is pending review (or a correction is open). It is a prompt, not
an error; resolve it by reviewing the claim, then re-compile. See
[security-and-troubleshooting.md](security-and-troubleshooting.md).
