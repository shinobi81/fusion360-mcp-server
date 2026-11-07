"""Mock-mode smoke test: print the new envelope shapes end-to-end."""

import json

from mcp import types

from fusion360_mcp.mock import mock_command
from fusion360_mcp.server import _format_result


def dump(label, name, params=None):
    print(f"\n=== {label} ===")
    result = mock_command(name, params or {})
    print("RAW RESULT:")
    print(
        json.dumps(
            {
                k: (f"<{len(v)} b64 chars>" if k == "image_base64" else v)
                for k, v in result.items()
            },
            indent=2,
            default=str,
        )
    )

    formatted = _format_result(name, result)
    print("\nFORMATTED (what the agent sees):")
    # ``_format_result`` returns either an error's CallToolResult or a plain list
    # of blocks; isinstance narrows both the container and each block, which is
    # what the previous hasattr/type-string dance was doing by hand.
    if isinstance(formatted, types.CallToolResult):
        print(f"[isError={formatted.isError}]")
        blocks = formatted.content
    else:
        blocks = formatted
    for block in blocks:
        if isinstance(block, types.TextContent):
            print(block.text)
        elif isinstance(block, types.ImageContent):
            print(f"<IMAGE BLOCK: {block.mimeType}, {len(block.data)} b64 chars>")


dump("1. SUCCESS with deltas (extrude)", "extrude", {"height": 3.0})
dump(
    "2. STRUCTURED ERROR with hints (forced)",
    "extrude",
    {"height": 3.0, "__mock_error__": "No profiles in sketch"},
)
dump("3. RENDER_VIEW image content", "render_view", {"view": "iso"})
dump(
    "4. NO-OP boolean (simulated)",
    "boolean_operation",
    {
        "target_body": "Body1",
        "tool_body": "Body2",
        "__mock_error__": "Boolean subtract failed — empty result",
    },
)
