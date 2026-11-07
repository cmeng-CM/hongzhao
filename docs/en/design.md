# Design

**English** | [简体中文](../design.md)

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

(04 and 06 are carried over from the author's original system diagrams; the
design philosophy and tradeoff table below also originate from that system's
design spec, carried forward through the hongzhao productization.)

## The problem it solves

hongzhao is not a full-conversation memory store, nor a project documentation
tool, task manager or session-handoff system. It solves one specific problem:
**when the same user starts new sessions across multiple AI coding agents
(Claude Code, Codex CLI, ZCode, ...), how do you calibrate identity and
direction with a small context — and then reliably find project facts and
long-term memory when needed?**

Its core capability is not "remember everything", but: **route the right
context to the agent at the right time, at the right granularity.** Without
such a mechanism the problem shows up as four recurring losses:

- **Re-introducing yourself every session** — identity, preferences and
  current direction get restated over and over; say too little and the agent
  misses the point, say too much and noise plus stale facts flood in.
- **Project facts guessed from summaries** — architecture, config and tasks
  live in the project, yet a memory summary gets treated as the source of
  truth; once the summary rots, the agent confidently concludes wrong things,
  with no way to trace blame.
- **Nobody owns what enters memory** — you don't know where a fact came from,
  whether it still holds, which fact wins, or how to delete it; conflicts are
  silently resolved by "newest wins" and errors keep propagating.
- **Client rules fight each other** — every agent host has its own rules file
  and permission model; writing into it directly breaks existing user config
  and makes the rule provenance untraceable.

## Tradeoffs at a glance

Every philosophy point is really a tradeoff. Summarized for line-by-line
review:

| Question | Choice | What was given up / why |
| --- | --- | --- |
| What goes into memory | Separate four fact classes (user / current session / project / handoff); long-term memory only for claims worth keeping across sessions | Gave up the "one big memory store". Mixing them bloats startup, rots facts, clashes rules, defeats accountability |
| What is the source of truth | raw is the only source; compiled / render are rebuildable views | Gave up feeding derived files back in as input; also gave up maintaining incremental + full rebuild as two semantic rule sets — full rebuild only |
| How fine-grained the permission model | Three scopes only (global / project / non-project) | No `private`, no visibility, no privacy isolation — unneeded at this scale |
| Does a human approve every entry | Write only when the user explicitly asks; low-ambiguity classification and merging proceed by convention, real questions (scope, ownership, long-term meaning) get asked | Gave up approving every bullet — nobody would use that |
| How facts expire | Explicit relations: a new claim `supersedes`, or a synthesis explicitly covers the old one | Gave up `expires` / `review_after` auto-expiry. A date says when it was recorded, not whether it is still true |
| Does distillation swallow sources | `derived_from` marks evidence only; `covers` means the source is fully absorbed; ordinary merging never edits old raw | Gave up "merge means delete/hide". A synthesis is itself new raw; the source chain survives intact |
| What when two facts conflict | Expose it, never silently pick: the compiler only interprets explicit relations; unresolved conflicts are locally excluded and health turns degraded | Gave up "newest wins". Newer is not truer |
| How to avoid fighting the client | One protocol + managed block: only the content between `hongzhao:start/end` markers is touched | Gave up rewriting client rule files. Existing rules, permissions and project-level `CLAUDE.md` / `AGENTS.md` stay untouched |
| Semantic vs mechanical | Skills own semantics (extract, classify, merge, judge conflicts); the engine owns deterministic execution (validate, rebuild) | Gave up letting scripts do semantic dedup or guess facts by timestamp — no silent merging |
| How deep to read by default | Light-to-heavy, on demand: bootstrap → project contract → real project files → effective views → raw | Gave up full injection by default. Stop at the lightest layer that answers the task |

In one sentence: **hongzhao does not remember everything for the agent — it
provides a conservative, auditable, on-demand context path.** Seven criteria
tell you it is working: a new session never re-asks for background and
direction; project tasks find real material through contracts; the default
context stays small with details on demand; every long-term claim traces back
to raw; conflicts, broken links and errors are visible, locatable,
reproducible; deleting derived files loses nothing; and the user can
understand, correct, demote or explicitly delete any memory.

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

See [SECURITY.md](../../SECURITY.md) and
[security-and-troubleshooting.md](security-and-troubleshooting.md): injected
content is treated as data, never instructions; rendering escapes
marker-breaking constructs; the package performs no network access.
