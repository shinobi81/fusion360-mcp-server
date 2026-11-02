# Fusion360 MCP Server

[![CI](https://github.com/shinobi81/fusion360-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/shinobi81/fusion360-mcp-server/actions/workflows/ci.yml)
[![Licence: AGPL-3.0-or-later](https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/protocol-MCP-8A2BE2.svg)](https://modelcontextprotocol.io)

An MCP server that lets AI coding agents drive **Autodesk Fusion 360**: create sketches
and features, assemble components, run CAM setups, measure, export, and look at the
result. 96 tools over the [Model Context Protocol](https://modelcontextprotocol.io), with
failures returned as structured data instead of exceptions.

> **Beta.** Pre-1.0: tool behaviour can change between tags. Install a tag, not PyPI — the
> published 0.1.0 pins `mcp>=1.0` with no upper bound and breaks under mcp 2.x.

## Quick start

```bash
# 1. Install the add-in into Fusion (symlink — re-run after editing addon/)
git clone https://github.com/shinobi81/fusion360-mcp-server
cd fusion360-mcp-server && ./scripts/install-addon.sh

# 2. In Fusion: Shift+S → Add-Ins → Fusion360MCP → Run
#    The TEXT COMMANDS window should show: [MCP] Server listening on 127.0.0.1:9876

# 3. Point your MCP client at this server (stdio)
claude mcp add fusion360 -- uvx --from 'git+https://github.com/shinobi81/fusion360-mcp-server@v0.3.1' fusion360-mcp-server --mode socket
```

Then call `ping` — `{"ok": true, "status": "pong"}` means you are connected.

Requirements: [uv](https://docs.astral.sh/uv/), Autodesk Fusion 360, and any MCP client
(Claude Code, Codex, Cursor, VS Code, …).

## What it can do

96 tools in 17 groups — the full catalogue with descriptions is in
**[docs/TOOLS.md](docs/TOOLS.md)**.

| Group | Examples |
| --- | --- |
| Document & scene | `new_document`, `get_scene_info`, `get_bounding_box`, `get_design_type` |
| Sketching | `create_sketch`, `draw_rectangle`, `draw_circles`, `add_constraint`, `offset_curve` |
| Features | `extrude`, `revolve`, `loft`, `sweep`, `fillet`, `shell`, `create_thread` |
| Body operations | `boolean_operation`, `split_body`, `offset_faces`, `scale_body`, `undo` |
| Primitives | `create_box`, `create_cylinder`, `create_sphere`, `create_torus` |
| Surfaces, sheet metal | `patch_surface`, `thicken_surface`, `create_flange`, `flat_pattern` |
| Construction | `create_construction_plane`, `create_construction_axis`, `create_ucs` |
| Assembly | `create_component`, `add_joint`, `set_joint_value`, `create_rigid_group` |
| Inspection | `measure_distance`, `measure_angle`, `check_interference`, `get_physical_properties` |
| CAM | `cam_create_setup`, `cam_create_operation`, `cam_post_process` |
| Import / export | `import_mesh`, `export_stl`, `export_step`, `export_f3d`, `export_view_sheet` |
| Perception & code | `render_view` (PNG of the viewport), `execute_code` |

## How it works

```text
MCP client ←(stdio MCP)→ this server ←(TCP 127.0.0.1:9876)→ Fusion add-in ←(CustomEvent)→ Fusion main thread
```

Fusion's API is not thread-safe, so the add-in marshals every call onto the main thread
through a CustomEvent work queue; socket threads block on a per-call event until the main
thread finishes. That is why one operation per tool call is a rule, not a preference.

## Install

### The add-in

`./scripts/install-addon.sh` symlinks `addon/` into Fusion's AddIns directory, so edits
are picked up on the next add-in restart. To copy instead:

```bash
# macOS
cp -r addon ~/Library/Application\ Support/Autodesk/Autodesk\ Fusion\ 360/API/AddIns/Fusion360MCP

# Windows (PowerShell)
Copy-Item -Recurse addon "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion360MCP"
```

Start it with **Shift+S → Add-Ins → Fusion360MCP → Run**. Set it to run at startup so the
port is there when your client connects.

### Your MCP client

The server speaks stdio, so any client can launch it:

```bash
uvx --from 'git+https://github.com/shinobi81/fusion360-mcp-server@v0.3.1' \
  fusion360-mcp-server --mode socket
```

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude mcp add fusion360 -- uvx --from 'git+https://github.com/shinobi81/fusion360-mcp-server@v0.3.1' fusion360-mcp-server --mode socket
```

</details>

<details>
<summary><strong>Cursor</strong> (<code>~/.cursor/mcp.json</code>)</summary>

```json
{
  "mcpServers": {
    "fusion360": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/shinobi81/fusion360-mcp-server@v0.3.1",
        "fusion360-mcp-server",
        "--mode",
        "socket"
      ]
    }
  }
}
```

</details>

<details>
<summary><strong>VS Code</strong> (<code>.vscode/mcp.json</code>)</summary>

```json
{
  "servers": {
    "fusion360": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/shinobi81/fusion360-mcp-server@v0.3.1",
        "fusion360-mcp-server",
        "--mode",
        "socket"
      ]
    }
  }
}
```

</details>

### Across machines (LAN)

If Fusion and the MCP client are on different hosts, bind the add-in to all interfaces on
the **Fusion host** (`FUSION_MCP_HOST=0.0.0.0`, set before Fusion starts) and point the
client at that host's LAN IP (`--host 192.168.1.42`, or `FUSION_MCP_HOST` in the client
config).

**The socket has no authentication.** Only do this on a trusted LAN, and never bind
`0.0.0.0` on a host reachable from the internet.

### Uninstall

Remove the client entry, stop the add-in (Shift+S → Add-Ins → Stop), and delete the
`Fusion360MCP` folder from Fusion's AddIns directory.

## Behaviour you should know

- **Units are centimetres** — Fusion's internal unit. A "10 mm" wall is `1.0`.
- **One operation per tool call.** Batching crashes the add-in: it is one main-thread work
  item at a time.
- **Timeouts.** The bridge gives up at 30 s and cancels the queued command; the client waits
  45 s so you get a structured `TIMEOUT`. **Mutations are never auto-retried** — call
  `get_scene_info` to see whether anything applied before retrying.
- **`undo` steps the timeline marker back** one feature (synchronous, so it reports
  `verified: true`). The feature is suppressed, not deleted: rolling the marker forward
  restores it, and creating a new feature while rolled back discards it. Direct-mode designs
  have no timeline, so `undo` issues Fusion's async command and reports
  `undone: "issued", verified: false` — confirm with `get_scene_info`.
- **Sketch draw tools ignore `z`.** Sketch curves live in the sketch plane; a `z` you pass
  is dropped and reported as `ignored_z`. Move the plane instead:
  `create_sketch(z_offset=...)`.
- **Logs** go to `~/fusion360mcp.log`.

## MCP features

- **Tools** with annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`). Per
the [MCP Tools spec](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
these are untrusted hints unless you trust the server — a read-only hint is not proof a
call is safe.
- **Resources:** `fusion360://status`, `fusion360://design`, `fusion360://parameters`, plus
  templates `fusion360://body/{name}` and `fusion360://component/{name}`.
- **Prompts:** `create-box`, `model-threaded-bolt`, `sheet-metal-enclosure`.
- **Structured errors:** `ok: false` with a stable `error_kind` (e.g. `BODY_NOT_FOUND`,
  `PROFILE_NOT_CLOSED`, `NOT_ENTITLED`, `TIMEOUT`), `hints`, and a traceback.
- **Mock mode:** `--mode mock` returns plausible data with no Fusion running.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Not connected` / `Connection refused` | The add-in isn't running. Shift+S → Add-Ins → Run. |
| Every call times out | Fusion's main thread is blocked — a modal dialog, or a long computation. |
| `create_sketch` geometry is offset | You passed `z` to a draw tool; it is ignored. Use `create_sketch(z_offset=…)`. |
| `NOT_ENTITLED` on `auto_constrain` | Fusion refuses that API for your account. Retrying will not help. |
| `os error 32` during `uv sync` | A running MCP server holds `.venv/Scripts/fusion360-mcp-server.exe`. Stop it first. |
| Direct push to `main` refused | Working as intended — this repo requires a reviewed PR. |

## Development

```bash
uv sync --dev                    # deps
uv run pytest -q                 # full suite, no Fusion needed
uv run ruff check src/ tests/    # lint (what CI runs)
npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"
```

The add-in can't be imported under pytest — it needs Fusion's `adsk` runtime — so tests
load `command_handler.py` against the fake runtime in `tests/fakes/`. Start with
**[CONTRIBUTING.md](CONTRIBUTING.md)**; architecture and tool conventions are in
**[AGENTS.md](AGENTS.md)**.

## This repo

A maintained continuation of
[faust-machines/fusion360-mcp-server](https://github.com/faust-machines/fusion360-mcp-server).
Upstream has had no merges since 2026-10-06 and the joint fixes are still waiting there
as [PR #35](https://github.com/faust-machines/fusion360-mcp-server/pull/35). Bugs and
questions belong in this repo's
[issue tracker](https://github.com/shinobi81/fusion360-mcp-server/issues); security
reports go through [SECURITY.md](SECURITY.md).

If you are an AI coding agent, read [AGENTS.md](AGENTS.md) — commands, conventions and
boundaries in one place. [llms.txt](llms.txt) is the index for crawlers.

## Acknowledgements

Inspired by [BlenderMCP](https://github.com/ahujasid/blender-mcp) — the socket bridge
architecture originated there — and by the wider Fusion MCP ecosystem:
[ArchimedesCrypto](https://github.com/ArchimedesCrypto/fusion360-mcp-server),
[Joe-Spencer](https://github.com/Joe-Spencer/fusion-mcp-server),
[JustusBraitinger](https://github.com/JustusBraitinger/FusionMCP),
[zkbkb](https://github.com/zkbkb/fusion-mcp),
[mycelia1](https://github.com/mycelia1/fusion360-mcp-server),
[sockcymbal](https://github.com/sockcymbal/autodesk-fusion-mcp-python).

## Licence

**AGPL-3.0-or-later** — see [LICENSE](LICENSE). Running a modified version as a network
service requires offering its source to that service's users (section 13). The attribution
the inherited upstream code requires is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md); it is not an alternative licence for this
project.
