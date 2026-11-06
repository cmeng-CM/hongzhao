# Claim schema

A **claim** is the atomic unit of memory: one fact, one owner moment, one file.

## Raw record

Files live under `raw/`, named `YYYY-MM-DD_<topic>_<8-hex>.md`. Frontmatter
(single line per value; all fields validated — over-length or multi-line values
are **rejected, never truncated**):

Required fields (all of them, validated exactly):

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | `2` | record schema |
| `id` | `mem-<uuid>` | stable identity |
| `created` | date | human date of the fact (not the file mtime) |
| `source` | enum | who wrote it (`user`, `claude-code`, `codex`, `zcode`, ...) |
| `topic` | slug | grouping key (e.g. `agent-core-learning`) |
| `kind` | `profile` \| `preference` \| `memory` | fact class |
| `scope` | `global` \| `non-project` \| `project` | routing scope |
| `activation` | enum | when it may enter context (e.g. `on-demand`, `bootstrap`) |
| `record_type` | `source` \| `synthesis` | raw note or synthesized view |
| `summary` | ≤ 300 chars, one line | the claim itself, in one sentence |
| `compile_status` | enum | review state (e.g. `done`) |

Optional relation fields (empty by default): `project_id` (required when scope
is `project`), `supersedes` (this fact replaces those), `derived_from`
(evidence chain; only synthesis may set it), `covers` (only synthesis may set
it), `conflicts_with`, `resolved_by`, `review_note`, `reviewed_at`. The
compiler additionally maintains computed fields on the index (`effective`,
`exclusion_reason`, `superseded_by`) — you never write those by hand.

The body is free markdown — context, quotes, caveats. The summary is what gets
rendered into views; the body stays in `raw/` as evidence.

## Five relations

```
supersedes   A ──▶ B     A replaces B (B becomes ineffective)
covers       A ──▶ B     A is a synthesis covering raw B (both may stay effective)
derived_from A ──▶ B     A's evidence includes B (trace only)
conflicts    A ◀─▶ B     A and B disagree; one must be resolved
resolves     A ──▶ C     correction A settles conflict C
```

The compiler only interprets these **explicit** relations — never timestamps,
never popularity, never silent preference. See
[06 — claim relations](assets/06-claim-relations.svg) and
[04 — claim lifecycle](assets/04-claim-lifecycle.svg).

## Effectiveness

A record is **effective** unless the compiler computes otherwise — typically
because it is superseded (`superseded_by` computed from the supersedes
relation), or it is a source record covered by a synthesis (`exclusion_reason`
is a compiler output, not a hand-set field). `compile` recomputes this on every run.

`compile` recomputes effectiveness for every record, then renders views. The
count of effective records is the number agents actually route through —
see `compiled/memory-index.yaml: records.*.effective`.

## Corrections

A correction is a normal claim with `resolved_by` set on the conflicting
records. Corrections are never destructive: the old text stays in `raw/`,
marked; the correction renders in `compiled/corrections.md` until both sides
age out. "Updated" does not mean "correct" — a correction is a new fact that
explicitly wins.

## Field limits and why

- **300 characters, one line, no control characters** on every rendered field:
  injection defense and diff hygiene (a claim you cannot grep in one line is a
  note, not a claim).
- Filenames carry the date and topic so sorting is meaningful without opening
  files; the trailing hex makes collisions impossible.
