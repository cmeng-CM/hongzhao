# Security and troubleshooting

**English** | [简体中文](../security-and-troubleshooting.md)

## Security model (summary — full text in [SECURITY.md](../../SECURITY.md))

- **No network.** The package contains no networking code; nothing is sent anywhere.
- **Data, not instructions.** Compiled views embed a notice that their content
  is data; rendering escapes constructs that could break out of the bootstrap
  block or forge markers (`@`-prefixed lines, marker-like tags). The compiler
  assumes raw notes may contain hostile text and renders it inert.
- **Field constraints as injection defense.** ≤ 300 chars, single line, no
  control characters — rejected, never truncated. A claim that cannot be
  grepped in one line is a note, not a claim.
- **Containment.** In-tree writes stay under the root; knowledge paths stay
  under `knowledge_root`; symlinks are refused as roots and inside skill sources.
- **Atomic writes, crash-safe ordering.** Registry before contract; every file
  written via temp + replace; `<root>/.hongzhao.lock` (flock) serializes
  registration across processes.
- **Fault injection for tests.** `HONGZHAO_TEST=1` + `HONGZHAO_FAULT=<point>`
  triggers crashes at the four critical write boundaries — used by the contract
  tests to prove recovery.

## Issue codes

`validate`, `compile` and `doctor` speak in stable, greppable codes
(`[CODE]`). The ones you will actually meet:

| Code | Severity | Meaning / fix |
| --- | --- | --- |
| `CONFIG_INVALID` | error | config schema mismatch — the message names the key |
| `ROOT_NOT_FOUND` / `ROOT_AMBIGUOUS` | error | root discovery failed — pass `--root` |
| `REGISTRY_BUSY` | error | another process holds the lock (10 s) — retry |
| `CONTRACT_DUPLICATE` | error | path already registered to another id — see J1–J6 |
| `KEY_CONFLICT` | error | key directory occupied by another project — choose another `--key` |
| `CONTRACT_KEY_DUPLICATE` | degraded (doctor) | registered contracts share a key — `project-unregister` one of them |
| `FIELD_TOO_LONG` / `FIELD_NOT_SINGLE_LINE` / `FIELD_CONTROL_CHAR` | error | field over 300 chars / multiline / control chars — edit the raw record (rejected, never truncated) |
| `FIELD_VALUE` | error | field value invalid (enum, type) — edit the raw record |
| `LEGACY_MARKER` | warning | client file still has an old-generation block — `migrate-bridge all` |
| `BRIDGE_STALE` / `SKILL_MISSING` / `SKILLS_CONFIG` | warning | `bridge-install` / `skills-install` |
| `OUTPUT_MISSING` | degraded | compiled artifact absent — run `compile` |
| `CONTRACT_ORPHAN` | degraded | central contract without registry entry — unregister or re-register |

## Troubleshooting walkthroughs

**Health is `review-needed`.** Not an error: a raw record is awaiting review or
a correction is open. `compile` output names the pending ids; review them
(edit the raw record or add a correction), then re-compile. `health: ok`
returns when nothing is pending.

**Seeing a degraded state (demo).** The fastest honest demo of the health
system:

```bash
hongzhao init /tmp/degraded-demo --example
hongzhao --root /tmp/degraded-demo compile
rm /tmp/degraded-demo/compiled/knowledge-map.md
hongzhao --root /tmp/degraded-demo doctor; echo "exit=$?"
# degraded OUTPUT_MISSING ... knowledge-map.md — exit=1
hongzhao --root /tmp/degraded-demo compile && hongzhao --root /tmp/degraded-demo doctor
# back to green, exit=0
```

Compiled views are rebuildable by design — deletion never loses data (the
source of truth is `raw/`).

**A client stopped routing memory.** Run `doctor`. Stale block →
`bridge-install`; missing skill link → `skills-install <client>`; you renamed
the root → fix `config.yaml`, then `doctor` again (links re-point).

**Registration says `KEY_CONFLICT`.** Another project already owns
`projects/<key>/`. Choose a different `--key`, or unregister the old one first
(`project-unregister` is dry-run by default; `--keep-contract` keeps the file).

**Compile crashed halfway.** Safe by construction: derived outputs are written
last, atomically. Re-run `compile`; if it keeps failing, `validate` will name
the offending record. Nothing in `raw/` is ever modified by compile.

**Recovery self-check.** `hongzhao project-check <path>` walks the discovery
order (central first, then project root) and tells you which contract a path
maps to — the first command to run when ownership looks wrong.
