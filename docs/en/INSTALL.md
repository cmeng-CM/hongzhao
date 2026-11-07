# Installing hongzhao

**English** | [简体中文](../INSTALL.md)

Two audiences, one file. Humans: three commands in [Manual install](#manual-install).
AI agents: your protocol is [Agent install protocol](#agent-install-protocol) — follow it
when a user asks you to install hongzhao.

## Install with your AI agent (one line)

Tell your coding agent (Claude Code, Codex CLI, ZCode, ...):

```text
Read https://github.com/cmeng-CM/hongzhao/blob/main/docs/en/INSTALL.md and install hongzhao for me. My client is claude_code.
```

Replace `claude_code` with your client (`codex`, `zcode`, or several). The agent
will run the protocol below and report a pass/fail table.

## Manual install

Requires macOS or Linux and Python 3.9+ (CI-tested on 3.12/3.13). Windows
native is unsupported in v0.1 — `init` fails fast rather than pretending.

```bash
pip install hongzhao          # or: uv tool install hongzhao / pipx install hongzhao
hongzhao init ~/hongzhao --client claude_code   # repeat --client per client
hongzhao --root ~/hongzhao compile              # MUST run before bridge-install
hongzhao --root ~/hongzhao bridge-install claude_code
hongzhao --root ~/hongzhao skills-install claude_code
hongzhao --root ~/hongzhao doctor               # expect: doctor: ok, exit 0
```

---

## Agent install protocol

You are an AI coding agent asked by a user to install hongzhao (a file-based
memory ledger for agents). Execute this protocol exactly. **Ground rules:**

1. **Inspect before you change anything.** Check for an existing memory kit
   (`~/hongzhao`, or any `hongzhao/config.yaml`), existing managed blocks
   (`hongzhao:start` markers) or legacy `agent-memory` blocks in the client
   file, and existing symlinks in the client skills directory. Report what you
   found **before** installing. Never overwrite, merge, or delete anything that
   is already there — if anything conflicts, stop and report instead.
2. **Use these exact commands** (adjust only the paths your user specified).
   Do not improvise alternatives. `--client` is a **repeatable flag**
   (`--client claude_code --client codex`); a comma-joined value
   (`--client a,b`) is invalid. `compile` must run **before** `bridge-install`:
   the managed block's content comes from the compiled bootstrap.
3. **Never edit the client file by hand.** The managed block is maintained by
   `bridge-install` only. Content outside the `hongzhao:start/end` markers must
   stay byte-identical. Similarly, never hand-edit anything under `compiled/`
   or `render/` — they are rebuilt by `compile`.
4. **Finish with verification** (below) and show the user a short pass/fail
   report. On any failed step: stop, show the exact command output, and
   suggest the fix from the troubleshooting table — do not force your way past
   a failure.
5. **Two choices are the user's, not yours.** The memory kit location and the
   set of clients to wire MUST be asked with the client's native selection
   dialog (e.g. AskUserQuestion). If your runtime has no dialog tool, ask in
   plain chat and wait for the reply. Never assume the default silently —
   defaults apply only when the user explicitly accepts them (empty answer =
   accept default).

### Steps

```bash
# 0. Prerequisites (report results before continuing)
python3 --version            # need >= 3.9; Windows native → stop (unsupported in v0.1)

# 1. Install (pick the first channel that works; report which one you used)
pipx install hongzhao        # fallback: python3 -m pip install --user hongzhao
                             # fallback: uv tool install hongzhao
hongzhao --version

# 2. Detect installed clients (report what you find before asking)
#    Detection is 2-of-3 per preset client: executable on PATH / config dir /
#    version command. Quick checks (a client counts if >=2 signals present):
command -v claude || true; [ -d ~/.claude ] && echo "claude_code signals"
command -v codex  || true; [ -d ~/.codex ]  && echo "codex signals"
command -v zcode  || true; [ -d ~/.zcode ]  && echo "zcode signals"

# 3. REQUIRED — ask the user (native dialog; plain chat question if no dialog
#    tool; wait for the answer, never answer for them):
#    a) Memory kit location — offer the default ~/hongzhao; user may type
#       another path or accept the default (empty answer = default).
#       When presenting the dialog, include this guidance: the default is
#       recommended — a standalone directory that is easy to version with git
#       and to back up; do NOT nest the kit inside an existing notes vault or
#       repository (couples the two systems and pollutes the host's history
#       with generated files). The kit is plain Markdown: Obsidian can open it
#       as a second vault for browsing, so nothing is lost by keeping it
#       standalone.
#    b) Which detected clients to wire — MULTI-SELECT from the detected list
#       (selecting none is valid: memory kit without client wiring).
#       The user may also insist on a client your checks did not detect —
#       accept it and enable manually after init (see troubleshooting).

# 4. Create the kit with the user's choices (repeat --client per selection;
#    omit all --client flags if the user selected none)
hongzhao init <PATH> --client <c1> --client <c2>
#    expect: "initialized memory kit at ..." ; requested-but-undetected
#    clients stay enabled:false with a warning — that is by design

# 5. Compile, then wire the selected clients
hongzhao --root <PATH> compile                   # expect: "compiled: ok"
hongzhao --root <PATH> bridge-install all        # only enabled clients are touched
hongzhao --root <PATH> skills-install all

# 6. Health check
hongzhao --root <PATH> doctor                    # expect: "doctor: ok"
```

### Verification (report each as pass/fail)

| # | Check | Command / expected |
| --- | --- | --- |
| 1 | CLI installed | `hongzhao --version` prints a version |
| 2 | Kit created | `~/hongzhao/config.yaml`, `raw/`, `compiled/` exist |
| 3 | Managed block present | client file contains exactly one `hongzhao:start` and one `hongzhao:end` marker; all pre-existing user content still present, unchanged |
| 4 | Skills linked | client skills dir has 4 symlinks (memory-write, memory-compile, memory-project-context, work-closeout) pointing into `~/hongzhao/skills/` |
| 5 | Health green | `hongzhao --root ~/hongzhao doctor` exits 0 |

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `render/bootstrap.md` missing at bridge-install | Run `compile` first (step 3 order matters) |
| `--client a,b` rejected as unknown client | Repeat the flag: `--client a --client b` |
| client not detected, left `enabled:false` | Client not installed on this machine (2-of-3 detection); install the client first, or set `enabled: true` by editing `config.yaml` |
| `CONFIG_INVALID: client ... fields incomplete` | Client entry must have exactly `enabled / bridge_path / skills_root / mode` |
| legacy `agent-memory` block already in file | Do not touch it; report and offer `hongzhao migrate-bridge all` |
| `doctor` shows `SKILL_MISSING` | Re-run `skills-install <client>` |
| `SKILL_CONFLICT` on skills-install: existing link/dir in client skills dir | Pre-existing `memory-*` entries belong to another kit. Confirm with the user, then `skills-install <client> --force` to re-point (the other kit's files are not touched) |
| `pip install --user` fails with `externally-managed-environment` | macOS Homebrew Python blocks user installs; use `uv tool install hongzhao` or `brew install pipx` first |
| runtime has no selection dialog tool | Ask both questions in plain chat and wait; do not proceed on an assumed answer |
| user insists on a client that was not detected (e.g. `zcode` CLI not on PATH but `~/.zcode` exists) | After init, set that client's `enabled: true` in `<PATH>/config.yaml`, then re-run `bridge-install all` / `skills-install all` |

### After install (tell the user)

Their agent now has four memory skills (trigger phrases): "记一下 / 记住" →
writes a **candidate** note (nothing enters context until compiled); "编译记忆"
→ semantic review + rebuild + client refresh; "给这个项目建档" → project
contract; "收尾" → session closeout routing. First compile review is the
user's gate: candidates never leak into context unreviewed.

After install, also suggest (one line each, do not run them unasked):

- **Version the kit**: `git init <PATH>` and commit after each weekly compile —
  memory is plain files; git is the backup.
- **Browse in Obsidian**: the kit is plain Markdown; Obsidian → "Open folder as
  vault" works on it directly (keep it a second vault rather than nesting it
  into an existing one).
- **Upgrading later**: `pipx upgrade hongzhao` then `hongzhao --root <PATH>
  upgrade` — see [UPGRADE.md](UPGRADE.md).

If reality diverges from this protocol (paths, clients, errors), adapt, explain
your reasoning to the user, and never force a step past a failure.
