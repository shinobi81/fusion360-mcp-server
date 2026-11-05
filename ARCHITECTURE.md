# Architecture

For contributors who need the shape of the system before touching it. Tool-level
conventions live in [AGENTS.md](AGENTS.md); the catalogue is
[docs/TOOLS.md](docs/TOOLS.md).

## Two processes, one thread boundary

```text
MCP client            this repo                      Fusion 360
──────────            ─────────────────              ──────────
stdio  ──────────▶  src/fusion360_mcp/server.py
                        │  connection.py
                        │  newline-delimited JSON over TCP 127.0.0.1:9876
                        ▼
                    addon/server/socket_server.py
                        │  socket thread per client
                        │  submit(command) → blocks on threading.Event
                        ▼
                    addon/server/event_bridge.py   ──CustomEvent──▶  Fusion main thread
                                                                      command_handler.py
```

Fusion's API is not thread-safe. Everything that touches it therefore runs on the main
thread, dispatched by a CustomEvent that Fusion fires on its own event loop. A socket
thread hand-builds a work item, raises the event, and waits on a per-item
`threading.Event` until the main thread has filled in the result. That single constraint
explains most of the system's design:

- **one operation per tool call** — the queue is drained one item per event; - **the
  30 s bridge timeout** — a blocked main thread (modal dialog) cannot answer, so the
  item is cancelled and the client gets a structured `TIMEOUT`; - **mutations are
  never retried** — the client cannot know whether the cancelled item ran.

## Where the pieces live

| Path | Role |
| --- | --- |
| `src/fusion360_mcp/server.py` | MCP surface: stdio transport, tools, resources, prompts, result formatting |
| `src/fusion360_mcp/connection.py` | TCP client, newline-delimited JSON, per-command timeouts |
| `src/fusion360_mcp/tools.py` | tool schemas — the contract agents read |
| `src/fusion360_mcp/hints.py` | error-kind table (mirror of the add-in's, kept in sync by a test) |
| `src/fusion360_mcp/mock.py` | `--mode mock` responses, so the envelope is testable without Fusion |
| `addon/server/socket_server.py` | listener, per-client threads, framing, malformed-input handling |
| `addon/server/event_bridge.py` | CustomEvent bridge and the work queue |
| `addon/server/command_handler.py` | every command, executing on the main thread |

`addon/` and `src/` are separate installables: the add-in is copied into Fusion's AddIns
directory and cannot import from the package, which is why the hint table exists twice
and why a test asserts the two are identical.

## The error envelope

Failures are data, not exceptions:

```json
{ "ok": false, "error_kind": "NOT_ENTITLED", "error_message": "...", "hints": ["..."], "traceback": "..." }
```

`error_kind` comes from `hints.py`, matched by regex against the exception text, in
order — first match wins. Adding a failure mode means adding a rule in both mirrors plus
a test; several kinds exist purely so an agent can branch instead of parsing prose
(`TIMEOUT`, `NOT_ENTITLED`, `DESIGN_TYPE_MISMATCH`).

Mutations additionally carry `deltas` (body count, mass, bbox before/after) so a no-op
is visible without a render.

## Sketch, timeline and undo semantics

Three Fusion behaviours that are easy to get wrong, each learned by measurement:

- **Sketch curves live in the sketch's own frame.** A `z` passed to a draw tool
  composes with the plane transform, so a caller repeating `z_offset` doubles it. The
  handler drops the normal component and reports `ignored_z`. - **The timeline marker
  is synchronous; `UndoCommand` is not.** `undo` steps the marker back, which is
  verifiable in the same call. On direct-mode designs `design.timeline` raises rather
  than returning `None`, and the fallback issues Fusion's async command and reports
  `verified: false`. - **`design.computeAll()` wipes joint values.** Never recompute
  after `set_joint_value`.

## Testing strategy

The add-in needs Fusion's `adsk` runtime, so it cannot be imported under pytest. Tests
load `command_handler.py` against the **fake runtime in `tests/fakes/`** and assert on
the arguments the Fusion API receives — the points handed to `sketchCircles`, the marker
written to `timeline`, the command definition executed. That is why the fakes model
Fusion's awkwardness on purpose: `design.timeline` raises in direct mode, and a queued
undo does not land until the next event pump.

`src/` is tested directly, including `--mode mock`. The suite runs on Python 3.14–3.15
and on Windows, because several behaviours (loopback resolution, the `.exe` handle) only
differ there.
