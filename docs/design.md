# Design

hongzhao is a memory ledger with a strict division of labor: **semantic judgment
belongs to the agent; validation, compilation and rendering belong to
deterministic scripts.** This page summarizes the architecture; the diagrams
below tell the story.

| Diagram | Story |
| --- | --- |
| [00 — overview loop](assets/00-overview-loop.svg) | from "note it down" to the next session |
| [01 — fact boundaries](assets/01-fact-boundaries.svg) | separate fact classes first, route context second |
| [02 — context routing](assets/02-context-routing.svg) | context layers from light to heavy |
| [03 — compile architecture](assets/03-compile-architecture.svg) | raw is the source of truth; compiled/render are rebuildable views |
| [04 — claim lifecycle](assets/04-claim-lifecycle.svg) | facts over time: explicit relations, no silent overwrites |
| [05 — work loop](assets/05-work-mode-loop.svg) | organize / retrieve / process as one loop |
| [06 — claim relations](assets/06-claim-relations.svg) | five relations: the algebra of memory |
| [07 — usage timeline](assets/07-usage-timeline.svg) | the daily cycle in four acts |

(04 and 06 are carried over from the author's original system diagrams.)

## Root discovery

Every command resolves the memory root from four sources, in priority order:
explicit `--root` → `$HONGZHAO_ROOT` → the working directory (walking up five
levels for `config.yaml`) → a managed block found in a preset client
instruction file (reverse lookup). Working-directory hits take precedence over
the bridge lookup so that sandboxes, mirrors and demos never resolve to a
production root. A candidate that fails validation is a hard error — no
fallback. `hongzhao root --json` prints the resolved root and its source.

## Data model

- **raw/** — claim records: dated, single-line-per-fact notes with frontmatter
  (see [claim-schema.md](claim-schema.md)). The only source of truth for memory content.
- **registry/** — `project-registry.yaml` (id → location) and
  `knowledge-registry.yaml`. Write path: registry first, then contract (crash-safe).
- **Project contracts** — `projects/<key>/project-view.md` (central) or
  `<project>/project-view.md` (project root). One contract per project; the
  registry decides who owns what.
- **compiled/ + render/** — derived views, fully rebuildable, never hand-edited.

## Contract lifecycle (J1–J6)

Registration is a state machine over (registry × existing contracts):

| Step | Condition | Action |
| --- | --- | --- |
| J1 | path has a contract | update flow |
| J2 | registry entry exists, central present | update central |
| J3 | registry entry exists, contract missing | rebuild, keep the id |
| J4 | orphan central exists (no registry) | adopt or report |
| J5 | key directory occupied by another project | `KEY_CONFLICT` |
| J6 | nothing exists | create registry entry + central contract |

Write order is always registry → contract, guarded by `flock` on
`<root>/.hongzhao.lock` (bound to the root, not to the environment). Crash at
any point leaves a state the next run can recover from (J3 reuse; atomic
replace everywhere; no temp residue).

## Validation and containment

`validate` checks schema exactness (unknown keys rejected), field constraints
(≤ 300 chars, single line, no control characters — rejects, never truncates),
and two containment rules: in-tree paths stay under the root; knowledge paths
stay under `knowledge_root`. Containment applies to writes; reads are never
blocked from following a valid path.

## Rendering

Nine artifact families are rendered deterministically from the index:
effective-memory views (global / non-project / per-project), the routing
index, current-state, corrections, knowledge map, and the client bootstrap.
Frontmatter key sets are frozen; link style is configurable (`link_style` /
`link_prefix`). User-visible text is English; code comments are Chinese.

## Security posture

See [SECURITY.md](../SECURITY.md) and
[security-and-troubleshooting.md](security-and-troubleshooting.md): injected
content is treated as data, never instructions; rendering escapes
marker-breaking constructs; the package performs no network access.
