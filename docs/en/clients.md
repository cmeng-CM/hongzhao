# Clients

**English** | [简体中文](../clients.md)

A **client** is an agent host with an instruction file (Claude Code's
`CLAUDE.md`, Codex CLI's `AGENTS.md`, ZCode's `AGENTS.md`, ...). hongzhao can
inject a managed **bootstrap block** into that file and link packaged skills
into the client's skills directory (symlinks on macOS/Linux, junctions on
Windows 10+ — neither needs elevated privileges).

## Preset clients

| Client | Instruction file | Detected at |
| --- | --- | --- |
| `claude_code` | `~/.claude/CLAUDE.md` | `~/.claude` |
| `codex` | `~/.codex/AGENTS.md` | `~/.codex` |
| `zcode` | `~/.zcode/AGENTS.md` | `~/.zcode` |
| `pi` | `~/.pi/agent/AGENTS.md` | `~/.pi` |
| `dsh` (DeepSeek Harness) | `~/.dsh/AGENTS.md` | `~/.dsh` |
| `opencode` | `~/.config/opencode/AGENTS.md` | `~/.config/opencode` |

Skills roots: `claude_code`/`codex`/`zcode` use their own directories; **pi natively reads `~/.agents/skills`** (the cross-agent shared dir); dsh follows the shared dir; opencode uses its native `~/.config/opencode/skills`.

`hongzhao init --client claude_code --client codex` (repeat the flag per client) detects which of the named clients
exist and enables exactly those (init never auto-installs; it only
configures). Custom clients are plain config entries — set `bridge_path` and
`skills_root` yourself in `config.yaml`.

## Managed blocks

The block is delimited by `hongzhao:start` / `hongzhao:end` markers:

```text
<!-- hongzhao:start (managed; edit outside the markers) -->
...bootstrap rendered from render/bootstrap.md...
<!-- hongzhao:end -->
```

- `bridge-install` inserts or refreshes the block; content outside the markers
  is never touched. It does **not** touch a legacy `agent-memory` block —
  migrating old-generation blocks is `migrate-bridge`'s job (run it for all
  clients at once; until then both generations may coexist).
- `uninstall` (dry-run by default) removes the block. Everything outside the
  markers survives byte-identical.
- `doctor` verifies each enabled client: block content equals the current
  bootstrap, and skill links (symlink/junction) resolve into `<root>/skills`.

## Skills

`skills-install all` (per-client: `skills-install claude_code`) copies packaged
skills/templates into `<root>/skills/` and links
`<client.skills_root>/<skill>` → `<root>/skills/<skill>` — one source of truth,
upgrade once, every client updates. Protections:

- a link pointing elsewhere is `SKILL_CONFLICT` (override with `--force`),
- foreign (non-link) directories are never touched,
- `uninstall` removes only links resolving inside `<root>/skills` (real directories are never deleted).

A manifest (`.hongzhao-manifest.json`) pins content hashes so upgrades are
explicit: `skills-install --manifest-only` records current hashes without
touching files (used by switch procedures).

## Refresh entry point

Every path that changes what the bootstrap should say (bridge-install,
knowledge-register, uninstall) goes through one function — the block is never
stale after a successful command.

## Diagnosing clients

`hongzhao doctor` prints severity-tagged lines and exits 1 only when a
`degraded` line is present (warnings alone keep exit 0):

```text
warning BRIDGE_STALE claude_code ~/.claude/CLAUDE.md managed block drifted; run hongzhao bridge-install
warning SKILL_MISSING codex ~/.codex/skills/memory-compile skill symlink missing: memory-compile
warning LEGACY_MARKER claude_code ~/.claude/CLAUDE.md legacy agent-memory block present; run hongzhao migrate-bridge all
degraded OUTPUT_MISSING - /path/to/compiled/knowledge-map.md derived output missing; run hongzhao compile
```

Each degraded/warning line names the affected client and file; the fixing command is the one shown in the line's message where present. See
[security-and-troubleshooting.md](security-and-troubleshooting.md) for the full
issue-code table.

## Shared skills directory (one link set, many clients)

`skills_root` is per client. On machines where several agents read one shared
skills directory (e.g. `~/.agents/skills`), point every non-Claude client's
`skills_root` at that shared dir — one `skills-install` link set then covers
all of them, and the same skill is never installed twice:

```yaml
clients:
  claude_code:
    skills_root: ~/.claude/skills    # Claude-specific
  zcode:
    skills_root: ~/.agents/skills    # shared by all non-Claude agents
  codex:
    skills_root: ~/.agents/skills    # same shared dir
```

Bridge and skills are independent: `bridge_path` is one rules file per client
(choose per client at install), while skills only need as many sources as there
are distinct skill directories. If a client ships its own skills dir you do not
use, install nothing there — an unused client needs no entry at all.
