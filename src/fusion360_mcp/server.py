"""
Fusion360 MCP Server — stdio transport.

Bridges MCP clients ↔ Fusion 360 add-in via TCP socket on 127.0.0.1.
Supports ``--mode mock`` for testing without Fusion running.
"""

import json
import logging
import os
import re
from pathlib import Path

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from pydantic import AnyUrl

from . import addon_install
from .connection import (
    _DEFAULT_HOST,
    _DEFAULT_PORT,
    FusionError,
    get_connection,
    reset_connection,
)
from .mock import mock_command
from .tools import get_tool_by_name, get_tool_list

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("fusion360_mcp.server")


def _send(
    mode: str,
    command_type: str,
    params: dict | None = None,
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> dict:
    """Route a command through either the real TCP connection or mock."""
    if mode == "mock":
        return mock_command(command_type, params)
    conn = get_connection(host=host, port=port)
    return conn.send_command(command_type, params)


def _fusion_error_result(name: str, exc: FusionError) -> types.CallToolResult:
    """Render a structured add-in error as an isError tool result."""
    lines = [f"**{name}** ERROR ({exc.error_kind})", f"  {exc}"]
    if exc.hints:
        lines.append("  hints:")
        lines.extend(f"    - {h}" for h in exc.hints)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="\n".join(lines))],
        isError=True,
    )


# Fields surfaced at the top of the formatted text block.  Everything else
# in the result dict is rendered below as ``key: value`` pairs.
_SPECIAL_KEYS = {
    "ok",
    "error_kind",
    "error_message",
    "hints",
    "traceback",
    "deltas",
    "image_base64",
}


def _format_deltas(deltas: dict) -> list[str]:
    """Render the deltas sub-dict as indented bullet lines."""
    lines = ["  deltas:"]
    bc_before = deltas.get("body_count_before")
    bc_after = deltas.get("body_count_after")
    bc_delta = deltas.get("body_count_delta")
    if bc_before is not None or bc_after is not None:
        lines.append(f"    body_count: {bc_before} → {bc_after} (Δ{bc_delta:+d})")
    mg_before = deltas.get("mass_g_before")
    mg_after = deltas.get("mass_g_after")
    mg_delta = deltas.get("mass_g_delta")
    if mg_delta is not None:
        lines.append(
            f"    mass_g:     {mg_before:.3f} → {mg_after:.3f} (Δ{mg_delta:+.3f})"
        )
    if deltas.get("bbox_before") is not None:
        lines.append(f"    bbox_before: {deltas['bbox_before']}")
    if deltas.get("bbox_after") is not None:
        lines.append(f"    bbox_after:  {deltas['bbox_after']}")
    return lines


def _format_result(
    name: str,
    result: dict | object,
) -> list[types.ContentBlock] | types.CallToolResult:
    """Render an addon/mock result into MCP content blocks.

    * Error responses (``ok: False``) → text block with hints + isError=True.
    * ``render_view`` success → text metadata + ImageContent for the PNG.
    * Everything else → text block listing result fields (+ deltas if any).
    """
    # Non-dict fallback (shouldn't happen, but stay robust).
    if not isinstance(result, dict):
        return [types.TextContent(type="text", text=f"**{name}** OK\n  {result}")]

    # Error path (application-level failure classified by the addon).
    if result.get("ok") is False:
        lines = [
            f"**{name}** ERROR ({result.get('error_kind', 'UNKNOWN')})",
            f"  {result.get('error_message', '(no message)')}",
        ]
        hints = result.get("hints") or []
        if hints:
            lines.append("  hints:")
            lines.extend(f"    - {h}" for h in hints)
        tb = result.get("traceback")
        if tb:
            lines.append("")
            lines.append("traceback:")
            lines.append(tb)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="\n".join(lines))],
            isError=True,
        )

    # Success path.
    lines = [f"**{name}** OK"]
    for k, v in result.items():
        if k in _SPECIAL_KEYS:
            continue
        lines.append(f"  {k}: {v}")
    # A successful call can still carry guidance (undo's issued-but-unverified
    # branch); the error path renders hints, so the success path must too.
    hints = result.get("hints") or []
    if hints:
        lines.append("  hints:")
        lines.extend(f"    - {h}" for h in hints)
    deltas = result.get("deltas")
    if isinstance(deltas, dict):
        lines.extend(_format_deltas(deltas))

    content: list[types.ContentBlock] = [
        types.TextContent(type="text", text="\n".join(lines)),
    ]

    # render_view: attach the PNG as an image block so vision models can see it.
    image_b64 = result.get("image_base64")
    if isinstance(image_b64, str) and image_b64:
        img_format = result.get("image_format", "png")
        content.append(
            types.ImageContent(
                type="image",
                data=image_b64,
                mimeType=f"image/{img_format}",
            )
        )
    return content


def build_server(mode: str, host: str, port: int) -> Server:
    """Build the MCP server: tool, resource, template and prompt handlers.

    Extracted from :func:`main` so the wiring is reachable without the CLI:
    an in-process client session can drive it through the real protocol.
    ``mode``/``host``/``port`` are captured by the handlers and forwarded to
    :func:`_send`.
    """

    app = Server("fusion360-mcp-server")

    # ── tools ────────────────────────────────────────────────────────

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return get_tool_list()

    @app.call_tool()
    async def call_tool(
        name: str,
        arguments: dict,
    ) -> list[types.ContentBlock] | types.CallToolResult:
        if get_tool_by_name(name) is None:
            raise ValueError(f"Unknown tool: {name}")

        try:
            result = _send(mode, name, arguments, host=host, port=port)
        except FusionError as exc:
            # Structured failure from the add-in (or a non-retried
            # mutation timeout) — the connection itself is healthy.
            return _fusion_error_result(name, exc)
        except Exception as exc:
            reset_connection()
            content: list[types.ContentBlock] = [
                types.TextContent(
                    type="text",
                    text=f"Error ({name}): {exc}\n\n"
                    "Make sure Fusion 360 is running and the "
                    "Fusion360MCP add-in is started.",
                )
            ]
            return types.CallToolResult(
                content=content,
                isError=True,
            )

        return _format_result(name, result)

    # ── resources ────────────────────────────────────────────────────

    @app.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl("fusion360://status"),
                name="Connection Status",
                description="Check whether Fusion 360 is reachable",
                mimeType="application/json",
            ),
            types.Resource(
                uri=AnyUrl("fusion360://design"),
                name="Design Tree",
                description="Full design tree: bodies, sketches, features, components",
                mimeType="application/json",
            ),
            types.Resource(
                uri=AnyUrl("fusion360://parameters"),
                name="User Parameters",
                description="All user-defined parameters in the design",
                mimeType="application/json",
            ),
        ]

    # Resource templates are matched by the same table the read dispatches on,
    # so a template can never be advertised without being renderable.
    _RESOURCES = {
        "fusion360://design": ("get_scene_info", None),
        "fusion360://parameters": ("get_parameters", None),
    }
    _RESOURCE_TEMPLATES = (
        (re.compile(r"^fusion360://body/(.+)$"), "get_object_info"),
        (re.compile(r"^fusion360://component/(.+)$"), "get_object_info"),
    )

    def _read(command: str, params: dict | None = None) -> dict:
        """The add-in's answer, or ``{"error": ...}`` after dropping the socket.

        One boundary for six reads instead of six copies of it: a failure must
        reset the connection exactly once, and a resource must degrade to an
        error document rather than raise into the protocol.
        """
        try:
            return _send(mode, command, params, host=host, port=port)
        except Exception as exc:
            reset_connection()
            return {"error": str(exc)}

    @app.read_resource()
    async def read_resource(uri: AnyUrl) -> str:
        uri_str = str(uri)
        if uri_str == "fusion360://status":
            result = _read("ping")
            payload = (
                {"connected": False, "error": result["error"]}
                if "error" in result
                else {"connected": True, "ping": result}
            )
            return json.dumps(payload, indent=2)

        if command := _RESOURCES.get(uri_str):
            return json.dumps(_read(*command), indent=2)

        for pattern, handler_name in _RESOURCE_TEMPLATES:
            if found := pattern.match(uri_str):
                result = _read(handler_name, {"name": found.group(1)})
                return json.dumps(result, indent=2)

        raise ValueError(f"Unknown resource: {uri_str}")

    @app.list_resource_templates()
    async def list_resource_templates() -> list[types.ResourceTemplate]:
        return [
            types.ResourceTemplate(
                uriTemplate="fusion360://body/{name}",
                name="Body Info",
                description="Detailed info about a named body",
                mimeType="application/json",
            ),
            types.ResourceTemplate(
                uriTemplate="fusion360://component/{name}",
                name="Component Info",
                description="Info about a named component",
                mimeType="application/json",
            ),
        ]

    # ── prompts ───────────────────────────────────────────────────────

    def _prompt(name: str, description: str, *args: types.PromptArgument):
        return types.Prompt(
            name=name,
            description=description,
            arguments=list(args),
        )

    def _dimensions(what: str) -> list[types.PromptArgument]:
        """The three box/enclosure arguments, which differ only in their noun."""
        return [
            types.PromptArgument(
                name=factor, description=f"{what} {factor} in cm", required=False
            )
            for factor in ("length", "width", "height")
        ]

    def _render_box(args: dict) -> str:
        return (
            "Create a parametric box in Fusion 360:\n"
            + "1. create_sketch on xy plane\n"
            + f"2. draw_rectangle width={args.get('width', '5')} "
            + f"height={args.get('length', '10')}\n"
            + f"3. extrude height={args.get('height', '3')}\n"
            + "4. get_scene_info to verify"
        )

    def _render_bolt(args: dict) -> str:
        desig = args.get("designation", "M10x1.5")
        return (
            f"Model a threaded bolt ({desig}):\n"
            + "1. create_sketch on xy plane\n"
            + "2. draw_circle for bolt shaft\n"
            + "3. extrude to bolt length\n"
            + f"4. create_thread designation={desig}\n"
            + "5. Create hex head sketch + extrude\n"
            + "6. chamfer head edges"
        )

    def _render_enclosure(args: dict) -> str:
        length = args.get("length", "20")
        width = args.get("width", "10")
        height = args.get("height", "5")
        return (
            f"Create a sheet metal enclosure ({length}x{width}x{height} cm):\n"
            + "1. create_sketch on xy plane\n"
            + f"2. draw_rectangle {width}x{length}\n"
            + "3. extrude to sheet thickness\n"
            + "4. create_flange on each edge\n"
            + "5. flat_pattern to verify unfold"
        )

    # name -> (what the client sees, how the text is rendered).  One table, so a
    # prompt cannot be advertised without a renderer or the reverse.
    _PROMPTS = {
        "create-box": (
            _prompt(
                "create-box",
                "Guide for creating a parametric box in Fusion 360",
                *_dimensions("Box"),
            ),
            _render_box,
        ),
        "model-threaded-bolt": (
            _prompt(
                "model-threaded-bolt",
                "Step-by-step guide for modeling a threaded bolt in Fusion 360",
                types.PromptArgument(
                    name="designation",
                    description="Thread designation (e.g. M10x1.5)",
                    required=False,
                ),
            ),
            _render_bolt,
        ),
        "sheet-metal-enclosure": (
            _prompt(
                "sheet-metal-enclosure",
                "Guide for creating a sheet metal enclosure",
                *_dimensions("Enclosure"),
            ),
            _render_enclosure,
        ),
    }

    @app.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        return [prompt for prompt, _render in _PROMPTS.values()]

    @app.get_prompt()
    async def get_prompt(
        name: str,
        arguments: dict | None = None,
    ) -> types.GetPromptResult:
        try:
            prompt, render = _PROMPTS[name]
        except KeyError:
            raise ValueError(f"Unknown prompt: {name}") from None
        return types.GetPromptResult(
            description=prompt.description,
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=render(arguments or {}),
                    ),
                ),
            ],
        )

    return app


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["socket", "mock"]),
    default="socket",
    help="'socket' connects to Fusion, 'mock' returns test data",
)
@click.option(
    "--host",
    type=str,
    default=lambda: os.environ.get("FUSION_MCP_HOST", "127.0.0.1"),
    help=(
        "Host where the Fusion 360 add-in listens (env: FUSION_MCP_HOST). "
        "Use the Windows LAN IP when the MCP server runs on a different machine."
    ),
)
@click.option(
    "--port",
    type=int,
    default=lambda: int(os.environ.get("FUSION_MCP_PORT", "9876")),
    help="TCP port the Fusion 360 add-in listens on (env: FUSION_MCP_PORT)",
)
@click.option(
    "--install-addon",
    is_flag=True,
    help="Copy the add-in into Fusion's AddIns folder, then exit.",
)
@click.option(
    "--addin-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override the AddIns directory.",
)
@click.pass_context
def main(
    ctx: click.Context,
    install_addon: bool,
    addin_dir: Path | None,
    mode: str,
    host: str,
    port: int,
) -> int:
    """Fusion360 MCP Server — connects MCP clients to Fusion 360."""
    # Refused rather than ignored: a server that starts after discarding the path looks
    # like an install that happened somewhere else.
    if addin_dir is not None and not install_addon:
        raise click.UsageError(
            "--addin-dir is only used by --install-addon: drop it to start the server, "
            "or pass --install-addon to copy the add-in into that folder"
        )
    # `ctx.exit`, not `return`: a standalone command's return value is not its exit
    # status, and the install's answer is the exit status the shell reads.
    if install_addon:
        ctx.exit(addon_install.install_addon(addin_dir=addin_dir))
    app = build_server(mode, host, port)

    # ── run ──────────────────────────────────────────────────────────

    from mcp.server.stdio import stdio_server

    async def arun():
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    anyio.run(arun)
    return 0
