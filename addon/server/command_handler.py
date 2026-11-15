"""
Fusion360 Command Handler

The composed handler: ``CommandHandler`` is ``HandlerBase`` plus one class per
domain and declares nothing itself.  Every command it answers is called on the
**main thread** (via EventBridge), so Fusion API access is safe.  A command lives in
the module that owns its domain; a helper two domains call lives in ``handler_base``.
"""

from .handler_assembly import AssemblyCommands
from .handler_base import HandlerBase
from .handler_cam import CamCommands
from .handler_export import ExportCommands
from .handler_features import FeatureCommands
from .handler_primitives import PrimitiveCommands
from .handler_scene import SceneCommands
from .handler_sketch import SketchCommands
from .handler_surface import SurfaceCommands


class CommandHandler(
    SketchCommands,
    FeatureCommands,
    PrimitiveCommands,
    SceneCommands,
    AssemblyCommands,
    SurfaceCommands,
    ExportCommands,
    CamCommands,
    HandlerBase,
):
    """Runs Fusion API operations.  Instantiated once; reused across requests."""
