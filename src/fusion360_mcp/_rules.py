"""Validation the add-in and mock mode share — GENERATED, do not edit.

Rendered by ``scripts/sync_mirrors.py`` from ``addon/server/rules.py``: the
add-in is installed into Fusion's AddIns folder and cannot import this
package, so its copy is canonical.  Edit that file and run
``uv run python scripts/sync_mirrors.py``; hand edits here are overwritten.
"""

# fmt: off
# `src/` is format-gated and `addon/` is not, so this rendered body is exempt:
# reformatting it here would edit a file the gate does not own.

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

# ``_hints.Refusal``, not ``from .hints import Refusal``: the add-in reloads these
# modules in place, and a by-name import would keep the class object that was
# imported first.  ``hints.classify`` tests ``isinstance(exc, Refusal)`` against the
# fresh class, so every refusal built here would fall back to the regex table - and
# that table answers the same today, so nothing would report the drift.
from . import hints as _hints

#: The four edge selectors ``fillet`` and ``chamfer`` accept.  ``tools.py`` advertises
#: this tuple as the schema enum and refuses nothing itself, so the validator owns the
#: set: a fifth selector is one edit here plus the branch that handles it.
EDGE_SELECTIONS = ("all", "top", "bottom", "vertical")

#: The formats ``export`` dispatches to, in the order ``tools.py`` advertises them.
#: ``stp`` is STEP's other extension; ``test_schema_gate`` pins the schema enum to this
#: tuple, so the gate and the validator refuse one set, not two.
EXPORT_FORMATS = ("stl", "step", "stp", "f3d")

#: The joint types both joint tools accept: ``add_joint`` defaults an omitted one to
#: ``rigid``, ``create_as_built_joint`` requires it.  ``tools.py`` advertises this tuple
#: as the schema enum, and ``tests/test_addon_joints.py`` pins this tuple, that enum and
#: the handler's own ``_JOINT_MOTION_SETTERS`` to each other - so the gate and this
#: validator refuse one set, not one each.
JOINT_TYPES = (
    "rigid",
    "revolute",
    "slider",
    "cylindrical",
    "pin_slot",
    "planar",
    "ball",
)

#: The angular positions a joint origin takes on a cylindrical face.
JOINT_QUADRANTS = ("start", "quarter", "middle", "third_quarter")

#: The axial positions a joint origin takes on a cylindrical face.
JOINT_KEY_POINTS = ("start", "middle", "center", "end")


#: The CAM strategies ``cam_create_operation`` advertises, in Fusion's own spelling.
#: Measured on 2706.1.17 against ``setup.operations.compatibleStrategies`` (56 names).
#: Of the **fifteen** names this schema used to carry, **five** were Fusion's own -
#: ``face``, ``bore``, ``slot``, ``trace``, ``engrave`` - and ten were invented
#: (``2d_contour``, ``2d_pocket``, ``2d_adaptive``, ``3d_adaptive``, ``3d_pocket``,
#: ``3d_contour``, ``3d_scallop``, ``3d_parallel``, ``drilling``, ``thread_milling``),
#: which Fusion refused with ``3 : Unknown strategy``.  The five 2D/3D names here are
#: the ones this tool now drives geometry for; a caller that needs one of the other 46
#: can name it through ``execute_code``, and the refusal says so.
CAM_STRATEGIES = (
    "face",
    "bore",
    "slot",
    "trace",
    "engrave",
    "contour2d",
    "pocket2d",
    "adaptive2d",
    "adaptive",
    "pocket_clearing",
)

#: The geometry parameter each strategy exposes, measured one operation at a time on
#: 2706.1.17.  ``face`` has none - only the stock boundary - so a face selection cannot
#: be given to it.  The handler discovers the same parameter at run time (only Fusion
#: knows its name); this map is what mock mode answers from.
CAM_GEOMETRY_PARAMETERS = {
    "contour2d": "contours",
    "pocket2d": "pockets",
    "adaptive2d": "pockets",
    "adaptive": "machiningBoundarySel",
    "pocket_clearing": "machiningBoundarySel",
}

#: The strategies ``face_indices`` can be given to: the map's keys, in one place.
CAM_GEOMETRY_STRATEGIES = tuple(CAM_GEOMETRY_PARAMETERS)


def cam_strategy_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an unknown CAM strategy earns, or None when it is usable.

    The schema's enum is advisory: a socket caller is not the schema, and the name goes
    straight into ``Operations.createInput``, where Fusion answers ``Unknown strategy``
    from inside the CAM product - a ``FUSION_REFUSED`` that names no fix.  Judged from
    the parameter alone, so mock mode refuses it too.
    """
    strategy = params.get("strategy")
    if strategy in CAM_STRATEGIES:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Unknown strategy {strategy!r} - use one of: {', '.join(CAM_STRATEGIES)}",
        hints=(
            "Fusion names 56 strategies; for one outside this set, create the "
            "operation through execute_code.",
        ),
    )


def cam_geometry_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a face selection earns when it cannot be applied, or None.

    Judged on the parameters alone, in the order a caller gets wrong first: a
    ``body_name`` with no ``face_indices`` (silently ignoring a supplied name is the
    shape this repo keeps out of the wire), then the list's shape (a socket caller can
    send anything), then the strategy, and last that a name was given at all.
    """
    faces = params.get("face_indices")
    body_name = params.get("body_name")
    strategy = params.get("strategy")

    if faces is None:
        if body_name is not None:
            return _hints.Refusal(
                "INVALID_INPUT",
                "body_name names the body face_indices select from - pass face_indices "
                "too, or omit body_name",
            )
        return None
    if not isinstance(faces, list):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"face_indices must be a list of face indices, not {type(faces).__name__}",
        )
    if not faces:
        return _hints.Refusal(
            "INVALID_INPUT",
            "face_indices is empty - name at least one face, or omit it",
        )
    for index in faces:
        if isinstance(index, bool) or not isinstance(index, int):
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Face index {index!r} is not a whole number - faces are indexed "
                "0-based in the body's own order",
            )
    if strategy not in CAM_GEOMETRY_PARAMETERS:
        return _hints.Refusal(
            "INVALID_INPUT",
            f"Strategy {strategy!r} takes no geometry selection - use face_indices "
            f"with one of: {', '.join(CAM_GEOMETRY_STRATEGIES)}",
        )
    if not body_name:
        # The same sentence ``_body_by_name`` would raise, from the parameters alone -
        # an empty name is not a name, and mock mode must answer what the add-in does.
        return body_name_required_refusal({"body_name": body_name})
    return None


#: What a reply says for an operation created without a tool.  Fusion's own sentence
#: (measured on 2706.1.17) is quoted rather than paraphrased, because it is what the
#: caller's *next* call answers - and one string, mirrored into ``src``, is what keeps
#: mock mode and the handler from drifting apart on it.
CAM_NO_TOOL_WARNING = (
    "No tool attached — generation answers 'Toolpath requires tool to be selected.' "
    "Pass tool_diameter (cm) or tool_json."
)


def _tool_json_shape_refusal(value: Any) -> _hints.Refusal | None:
    """The refusal a ``tool_json`` that cannot be a tool object earns, or None.

    Shape only: whether the object is a *valid* tool is Fusion's to say, and one
    measured answer is that a partial object crashes rather than refusing - which is
    why the add-in's own builder emits the whole shape and why a caller supplying JSON
    is told to bring a complete one.  A string that is not JSON, or JSON that is not a
    non-empty object, never reaches Fusion.
    """
    if not isinstance(value, str):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"tool_json must be a JSON string, not {type(value).__name__}",
        )
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        return _hints.Refusal(
            "INVALID_INPUT",
            f"tool_json is not valid JSON: {exc}",
            hints=("Copy one complete entry from a Fusion tool library's data array.",),
        )
    if not isinstance(parsed, dict):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"tool_json must be one tool object, not {type(parsed).__name__}",
            hints=("One entry of a Fusion tool library's data array is the shape.",),
        )
    if not parsed:
        return _hints.Refusal(
            "INVALID_INPUT",
            "tool_json is an empty object - it must describe a complete tool",
            hints=(
                "A partial tool object crashed Fusion 2706.1.17; send the whole one.",
            ),
        )
    # Key *presence* is deliberately not enforced. Measured across Fusion's own 15
    # sample libraries (807 tools): 257 carry no ``holder``, 75 no ``geometry`` and 72
    # no ``start-values`` with a preset - so requiring the three blocks would refuse
    # tools Fusion ships itself. The crashed probe was a partial object, but it omitted
    # several things at once and this guard cannot tell which omission was fatal, so it
    # stays structural and the advice points at the builder measured to work.
    return None


#: Ceilings for the tool arguments, and they exist for one reason: the emitted tool is
#: JSON, ``Infinity`` is not JSON, and ``json.dumps`` writes it without complaint - so
#: a value large enough to overflow the numbers the builder derives from it would reach
#: ``Tool.createFromJson`` as invalid input, on the one call here with a measured
#: Fusion-exit history. Enumerating the builder's scaling factors was tried and was a
#: constant short (a diameter is multiplied by 10, by 3 for the flute length, and by
#: ``pi * n / 1000`` for the surface speed); a ceiling cannot be short. Every maximum
#: below leaves the derived numbers finite with room to spare - a 10 m cutter, a
#: 1000-flute tool and a tool number of 100000 are far past anything this contract
#: describes.
_TOOL_MAXIMUM = {
    "tool_diameter": 1000,  # cm
    "tool_length": 1000,  # cm
    "tool_flutes": 1000,
    "tool_number": 100000,
}


#: The ``stock_mode`` vocabulary, and the Fusion id each name maps to - measured on
#: 2706.1.17 by writing ``job_stockMode`` on a live setup. ``default``, ``fixedbox``,
#: ``relativecylinder``, ``fixedcylinder`` and ``solid`` are accepted; ``from_body`` -
#: what this schema used to advertise - and a nonsense string were both refused by
#: Fusion with ``3 : Invalid enumeration value.`` (two probes, not "every other
#: string"), which the handler could only report as
#: ``stock_failed``. One table, so the schema, the handler and mock mode cannot drift.
CAM_STOCK_MODES = {
    "relative_box": "default",
    "fixed_box": "fixedbox",
    "relative_cylinder": "relativecylinder",
    "fixed_cylinder": "fixedcylinder",
    # Fusion's UI calls this "From solid". The old spelling ``from_body`` never worked:
    # it is not an id Fusion knows, and it reached Fusion verbatim as that string.
    "from_solid": "solid",
}


def cam_stock_mode_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an unknown ``stock_mode`` earns, or None when it is one of the five.

    Judged from the parameter alone, so mock mode refuses exactly what the handler
    refuses - and before a setup exists, so a typo cannot leave one behind with no stock
    applied. The alternative the code used to take was passing the string through to
    Fusion, which answers ``Invalid enumeration value`` and leaves the caller reading
    ``stock_failed`` with no idea which values work.
    """
    mode = params.get("stock_mode", "relative_box")
    # A table lookup hashes the key, so a list or an object - which a socket caller can
    # send and no schema can stop - would raise TypeError out of a refusal function and
    # reach the caller as UNKNOWN with no hints.
    if not isinstance(mode, str):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"stock_mode must be a string, not {type(mode).__name__}",
            hints=("Pass one of: " + ", ".join(CAM_STOCK_MODES),),
        )
    if mode in CAM_STOCK_MODES:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Unknown stock_mode {mode!r} - use one of: {', '.join(CAM_STOCK_MODES)}",
        hints=(
            "Fusion's own ids, measured: " + ", ".join(CAM_STOCK_MODES.values()) + ".",
            "`from_body` was advertised before this was measured and never worked; "
            "the working name for that mode is `from_solid`.",
        ),
    )


def cam_tool_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a contradictory tool request earns, or None when it is usable.

    ``cam_create_operation`` can get a tool three ways and only one at a time: a
    ``tool_json`` the caller measured, a ``tool_diameter`` the add-in turns into one, or
    neither (a bare operation, which cannot generate).  Judged from the parameters
    alone, so mock mode refuses exactly what the handler refuses - and so a caller
    learns the combination without a design, or an operation left behind.

    ``tool_number`` numbers a tool the add-in creates; there is no library lookup yet,
    so a number on its own names nothing.  It used to reach Fusion as a parameter name
    that does not exist, which reported a silent ``parameters_failed``.

    ``tool_json`` is checked for *shape* here as well, because it is forwarded verbatim
    to ``Tool.createFromJson`` - the one call in this path with a measured crash history
    (a partial object exited Fusion 2706.1.17).  A string Fusion will not parse is
    answerable from the parameters alone, so mock mode answers it too.
    """
    tool_json = params.get("tool_json")
    shape_given = [
        name
        for name in ("tool_diameter", "tool_length", "tool_flutes")
        if params.get(name) is not None
    ]
    if tool_json is not None:
        if refusal := _tool_json_shape_refusal(tool_json):
            return refusal
        # ``tool_number`` is in the conflict list because the number lives inside the
        # JSON's ``post-process`` block: passing both would drop the argument the
        # caller sent, and a supplied-but-ignored value is not something this wire
        # does.
        conflicts = list(shape_given)
        if params.get("tool_number") is not None:
            conflicts.append("tool_number")
        if conflicts:
            return _hints.Refusal(
                "INVALID_INPUT",
                "tool_json defines the whole tool - drop "
                f"{', '.join(conflicts)} or the tool_json",
                hints=(
                    "tool_json is for a complete tool object taken from a Fusion "
                    "tool library; its post-process number is the tool number.",
                ),
            )
        return None
    # The schema's ``minimum`` and ``type`` are advice to a client, not a guard: a
    # socket caller is not the schema, and a malformed value either serialises
    # ``Infinity`` into the tool JSON or builds a zero-diameter tool - and a malformed
    # tool object is the shape with a measured crash history.  Both sides answer from
    # here, so mock mode cannot accept what Fusion would be asked to swallow.
    for name in ("tool_diameter", "tool_length", "tool_flutes", "tool_number"):
        value = params.get(name)
        if value is None:
            continue
        whole = name in ("tool_flutes", "tool_number")
        if isinstance(value, bool) or not isinstance(value, int | float):
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{name} must be a number, got {value!r}",
                hints=("Lengths are centimetres; a count is a whole number.",),
            )
        try:
            # ``require_finite`` skips an int on purpose, and an int too large for a
            # float raises OverflowError - which in the builder would reach a caller as
            # ``UNKNOWN`` and in mock mode as success. Judged here, both sides refuse.
            magnitude = float(value)
        except OverflowError:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{name} is outside the numeric range Fusion can store, got {value!r}",
                hints=("Send a value in Fusion's numeric range.",),
            )
        if magnitude > _TOOL_MAXIMUM[name]:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{name} must be at most {_TOOL_MAXIMUM[name]}, got {value!r}",
                hints=(
                    "Lengths are centimetres: a real cutter is a few of them, not "
                    "hundreds.",
                ),
            )
        if magnitude <= 0:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{name} must be greater than 0, got {value!r}",
                hints=(
                    "tool_diameter and tool_length are centimetres; tool_number is "
                    "the number the post writes.",
                ),
            )
        if whole and not isinstance(value, int):
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{name} must be passed as an integer, got {value!r}",
                hints=("A flute count and a tool number are counts, not lengths.",),
            )
    if params.get("tool_diameter") is None:
        if shape_given:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"{', '.join(shape_given)} shapes the tool tool_diameter creates - "
                "pass tool_diameter too",
                hints=("tool_diameter is in centimetres, like every other length.",),
            )
        if params.get("tool_number") is not None:
            return _hints.Refusal(
                "INVALID_INPUT",
                "tool_number numbers a tool this command creates - pass tool_diameter "
                "(cm) or tool_json too",
                hints=(
                    "Without a tool source the operation is created with no tool, "
                    "and Fusion then refuses to generate its toolpath.",
                ),
            )
    return None


def joint_selector_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an unknown joint type, quadrant or key point earns, or None.

    The schema's enum is advisory: a socket caller is not the schema, so an unknown
    value reaches the handler - and both joint commands index a table with it, which
    used to raise a bare ``KeyError`` classified as ``UNKNOWN``.  ``joint_type`` reached
    ``_JOINT_MOTION_SETTERS`` the same way.  Judged from the parameters alone, so mock
    mode refuses it too, and so a caller learns the accepted set without a design.
    """
    for name, accepted, default in (
        ("joint_type", JOINT_TYPES, "rigid"),
        ("quadrant", JOINT_QUADRANTS, "middle"),
        ("key_point", JOINT_KEY_POINTS, "end"),
    ):
        value = params.get(name, default)
        if value not in accepted:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Unknown {name} {value!r} - use one of: {', '.join(accepted)}",
            )
    return None


def edge_selector_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an edge selector's parameters earn, or None when they are usable.

    ``params`` carries ``edge_selection``, ``edge_indices`` and ``edge_points`` as the
    caller sent them, ``None`` meaning unset.  Only the parameters are judged: whether
    the body has any edges, and which edges a selection matches, needs Fusion.

    One selector at a time.  A caller that passes two has not decided which edges it
    means, and picking one would silently round whatever the other happened to match.
    ``all`` is the default, so it is the one selection that means "unset".  Indices are
    positional, so a stale one and an empty list are both caller mistakes Fusion cannot
    detect — the message names the selector to use instead.
    """
    indices = params.get("edge_indices")
    points = params.get("edge_points")
    selection = params.get("edge_selection", "all")

    if indices is not None and points is not None:
        return _hints.Refusal(
            "INVALID_INPUT",
            "Pass only one of edge_indices and edge_points — they name the same "
            "edges two ways, so one would be ignored",
        )
    if (indices is not None or points is not None) and selection != "all":
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_selection '{selection}' cannot be combined with edge_indices "
            "or edge_points — pass one selector, not two",
        )
    if indices is not None and not isinstance(indices, (list, tuple)):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_indices needs a list of whole numbers, got {indices!r}",
        )
    if points is not None and not isinstance(points, (list, tuple)):
        return _hints.Refusal(
            "INVALID_INPUT",
            f"edge_points needs a list of three-number points, got {points!r}",
        )
    if indices is not None and not indices:
        return _hints.Refusal(
            "INVALID_INPUT",
            "edge_indices was empty — name at least one edge, or omit it to use "
            "edge_selection",
        )
    if points is not None and not points:
        return _hints.Refusal(
            "INVALID_INPUT",
            "edge_points was empty — name at least one point, or omit it to use "
            "edge_selection",
        )
    for index in indices or []:
        if isinstance(index, bool) or not isinstance(index, int):
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Edge index {index!r} is out of range — indices are whole numbers "
                "from list_edges",
            )
    for point in points or []:
        # Shape before count: a bare number is not a point, and ``len`` of one is a
        # TypeError — so ``3`` must not read as "three coordinates".
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            got = len(point) if isinstance(point, (list, tuple)) else repr(point)
            return _hints.Refusal(
                "INVALID_INPUT",
                f"Each edge point needs three coordinates, got {got}",
            )
    if selection not in EDGE_SELECTIONS:
        return _hints.Refusal(
            "INVALID_INPUT",
            f"Unknown edge_selection '{selection}' — use all/top/bottom/vertical",
        )
    return None


def target_body_refusal(
    params: Mapping[str, Any], operation: str
) -> _hints.Refusal | None:
    """The refusal a ``target_body`` beside a new body earns, or None.

    ``operation`` decides it, not the body: a new body is the feature's output, so
    there is nothing to target, and Fusion is never asked.  An unknown *name* is not
    judged here — that takes the design, which mock mode does not have.
    """
    if params.get("target_body") is None or operation != "new_body":
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Invalid input: target_body applies only to cut, join or intersect — "
        "new_body builds a body of its own, so there is nothing to target",
    )


def components_differ_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a joint between one component and itself earns, or None.

    Two occurrences of the same component have no relative motion, so Fusion is
    never asked.  The names are compared, not the occurrences: a handler has
    already resolved them, and mock mode has no design to resolve them in.
    """
    component_one = params.get("component_one")
    component_two = params.get("component_two")
    if component_one is None or component_two is None or component_one != component_two:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "component_one and component_two must differ",
        hints=("Pass two different components; a joint needs two.",),
    )


def joint_geometry_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an ``add_joint`` without a face pair earns, or None.

    A joint cannot be built from the components' origin points: a bare point
    carries no component association, so ``JointGeometry.createByPoint`` rejects
    it.  Whether the named face exists needs Fusion; that it was named does not.
    The tool's schema also requires ``face_one`` and ``face_two``, so the gate
    refuses a missing pair first for MCP callers; this sentence answers a caller
    that reached the add-in directly.
    """
    if params.get("face_one") is not None and params.get("face_two") is not None:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "add_joint needs joint geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Component origin points are not valid joint geometry.",
        hints=(
            "Pass face_one and face_two.",
            "Add body_one/body_two when the component holds more than one body.",
        ),
    )


def as_built_geometry_refusal(
    params: Mapping[str, Any],
) -> _hints.Refusal | None:
    """The refusal a non-rigid as-built joint without a face pair earns, or None.

    Fusion refuses the input with "Geometry should not be null if joint motion is
    not rigid", so only ``rigid`` works without geometry.  ``joint_type`` decides
    it: ``add_joint`` defaults it to ``rigid``; ``create_as_built_joint`` requires
    it, and the parameter bind refuses the omission first.
    """
    joint_type = params.get("joint_type", "rigid")
    if joint_type == "rigid":
        return None
    if params.get("face_one") is not None and params.get("face_two") is not None:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"A {joint_type} as-built joint needs geometry: pass face_one/face_two "
        "(and body_one/body_two when a component holds more than one body). "
        "Only 'rigid' works without it.",
        hints=("Pass face_one and face_two, or use joint_type='rigid'.",),
    )


def rigid_group_size_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a rigid group of fewer than two components earns, or None.

    ``params`` carries the names that resolved to occurrences, so this is what the
    add-in checks before ``rigidGroups.add``; mock mode judges the names it was
    given, which is all it has.  A group of one holds nothing together.  The
    schema's ``minItems: 2`` makes the gate refuse a shorter list first for MCP
    callers; this sentence is the direct-wire answer.
    """
    names = params.get("component_names") or ()
    if len(names) >= 2:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Need at least 2 components for rigid group",
        hints=("Pass at least two component names.",),
    )


#: The base construction planes, by the name a caller passes.  One table, read by the
#: refusal below and by the handler's lookup, so a name cannot be accepted by one and
#: refused by the other.
_CONSTRUCTION_PLANES: frozenset[str] = frozenset({"xy", "yz", "xz"})


def construction_plane_name_refusal(plane: Any) -> _hints.Refusal | None:
    """The refusal an unusable ``plane`` name earns, or None when it is one of the 3.

    ``_construction_plane`` resolved the name against a table and refused a miss itself,
    which meant mock mode answered ``created: true`` for ``plane="zz"``: a value Fusion
    is never asked about, because the add-in refuses it first.  A parameter the add-in
    can refuse from the parameters alone belongs here, so both sides answer one sentence
    - and the tangent rule below can reach this from its own judgement.
    """
    if str(plane or "").lower() in _CONSTRUCTION_PLANES:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Unknown plane {plane!r} — use xy, yz, or xz",
        hints=("Pass xy, yz or xz; the plane is lowercased, so XZ works.",),
    )


def construction_plane_tangent_refusal(
    params: Mapping[str, Any],
) -> _hints.Refusal | None:
    """The refusal a ``tangent`` construction plane earns, or None when buildable.

    Fusion ships **two** definitions behind the one advertised value, and the parameters
    decide which runs: ``point_one`` selects ``setByTangentAtPoint(face, point)``,
    otherwise ``angle`` (default 0, degrees) and ``plane`` select
    ``setByTangent(face, angle, referencePlane)``, which is a cylinder's - measured on
    2706.1.17: a cone is refused however the reference plane is chosen.
    Judged from the parameters alone, so mock mode refuses exactly what the add-in
    refuses and a caller learns the shape without a design - and so the one method that
    was advertised and refused outright (one of two enum values a caller could send and
    never satisfy) can finally be built.

    ``face_index``'s *range* is not judged here: that needs the body, and the handler
    names it against the body it resolved, as ``perpendicular_at_point`` does.
    """
    if params.get("method") != "tangent":
        return None
    point = params.get("point_one")
    if point is not None and (params.get("plane") or params.get("angle") is not None):
        return _hints.Refusal(
            "INVALID_INPUT",
            "A tangent plane is built one way: pass point_one, or angle and plane - "
            "not both",
            hints=(
                "point_one builds the plane through that point.",
                "angle and plane build it at an angle measured from a reference plane.",
            ),
        )
    # Every absent argument in ONE sentence, so a shape-less call costs one retry and
    # not one per argument.  ``body_name`` is deliberately absent from this list: an
    # empty or missing one earns the shared "A body name is required" every other tool
    # answers, so one fault keeps one sentence - the same split the axis rule makes.
    # An empty string is not a plane: ``_construction_plane`` refuses it, so the rule
    # does too rather than letting mock mode build one.
    missing = []
    if params.get("face_index") is None:
        missing.append("face_index")
    if point is None and not params.get("plane"):
        missing.append("plane")
    if missing:
        joined = " and ".join(missing)
        return _hints.Refusal(
            "INVALID_INPUT",
            f"tangent needs {joined}",
            hints=(
                "list_faces reports every face's index and surface_type.",
                "plane is xy, yz or xz, and angle defaults to 0 degrees.",
            ),
        )
    if point is not None:
        return point3d_refusal({"point_one": point})
    return None


def perpendicular_axis_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a ``perpendicular_at_point`` axis earns, or None when buildable.

    Fusion's ``setByPerpendicularAtPoint(face, pointEntity)`` takes a B-Rep face, and
    until this tool had ``face_index`` the method was advertised and refused outright.
    Both enum values a caller could send and never satisfy are closed now: this one,
    and ``create_construction_plane``'s ``tangent`` (with ``face_index`` too). The
    three arguments it needs are judged from the parameters alone, so mock mode
    refuses the same call and names the same missing ones.
    """
    if params.get("method") != "perpendicular_at_point":
        return None
    # `body_name` is deliberately not here: an empty or absent one earns the shared
    # "A body name is required" every other tool answers, so one fault has one sentence.
    # An empty list is not a point, and `is None` for the index - face 0 is a face.
    missing = ["point_one"] if not params.get("point_one") else []
    if params.get("face_index") is None:
        missing.insert(0, "face_index")
    if not missing:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"perpendicular_at_point needs {', '.join(missing)} - it builds an axis normal "
        "to a face at a point",
        hints=(
            "list_faces reports a body's face indices; point_one is [x, y, z] in cm.",
        ),
    )


def body_name_required_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a body-naming call with no name earns, or None when one was given.

    ``handler_base._body_by_name`` takes the name every body command was handed, and
    an empty one names nothing: Fusion would be given ``""`` and answer about the
    argument, without saying which call was short.  Whether a body *of* that name
    exists needs the design; that a name was given does not, so mock mode judges it
    too.
    """
    if params.get("body_name"):
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "A body name is required",
        hints=("Pass a body name; get_scene_info lists the bodies in this design.",),
    )


def point3d_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a point that is not three numbers earns, or None when all are.

    ``params`` maps each point parameter's name to the value the caller sent, so the
    message names the one that is wrong: ``Point3D.create(*values)`` unpacked a short
    list inside Fusion's binding, and the caller read a ``TypeError`` instead.  Three
    numbers in the right shape is judged here; whether they describe a usable point
    is Fusion's.  ``_POINT3`` declares the same shape, so the gate refuses a
    non-point first for MCP callers; this sentence is the direct-wire answer.
    """
    for field, values in params.items():
        if isinstance(values, (list, tuple)) and len(values) == 3:
            continue
        return _hints.Refusal(
            "INVALID_INPUT",
            f"{field} must be [x, y, z] in centimetres",
            hints=("Pass three numbers, in centimetres: [x, y, z].",),
        )
    return None


def rule_type_refusal(rule_type: str) -> _hints.Refusal | None:
    """The refusal a ``ruled_surface`` ``rule_type`` earns, or None when it is usable.

    The schema's enum is advisory: a socket caller is not the schema, so an unknown
    value reaches the handler, and a bare ``KeyError`` classified as ``UNKNOWN`` tells
    it nothing.  Judged from the parameter alone, so mock mode refuses it too instead
    of rehearsing a call Fusion rejects.
    """
    if rule_type in ("normal", "tangent"):
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Unknown rule_type {rule_type!r} - use 'normal' or 'tangent'",
    )


def surface_tool_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a ``trim_surface`` tool choice earns, or None when it has one.

    A trim takes exactly one tool, and the two parameters are alternatives; a call
    with both or neither has not said what to trim with, so Fusion is never asked.
    ``params`` carries ``tool_name`` and ``tool_plane`` as the caller sent them,
    ``None`` meaning unset.  Whether either names something that exists needs the
    design.
    """
    if bool(params.get("tool_name")) != bool(params.get("tool_plane")):
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "trim_surface needs exactly one of tool_name (a body) or tool_plane "
        "(xy, xz or yz)",
        hints=("Pass tool_name (a body), or tool_plane (xy, xz or yz), but not both.",),
    )


#: What ``int()`` raises for a value that is not an index.  A tuple in a name,
#: not ``except (TypeError, ValueError):``, because ``src/fusion360_mcp/_rules.py``
#: mirrors this file and is format-gated: ruff's PEP 758 pass rewrites the
#: parenthesised form to ``except TypeError, ValueError:``, which Fusion's own
#: interpreter rejects.
_INDEX_ERRORS = (TypeError, ValueError)


def keep_cells_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a ``trim_surface`` cell selector earns, or None when it is usable.

    ``params`` carries ``keep_cells`` as the caller sent it.  A cell is named by its
    index, so a word is a caller mistake Fusion cannot report; the indices are
    converted here the way the handler converts them, which is why a numeric string
    is accepted.  Whether an index is in range needs the cells Fusion computes.
    The schema types each entry as an integer with a minimum of 0, so the gate
    refuses those first for MCP callers; this sentence is the direct-wire answer.
    """
    for index in params.get("keep_cells") or ():
        try:
            int(index)
        except _INDEX_ERRORS:
            return _hints.Refusal(
                "INVALID_INPUT",
                f"keep_cells takes cell indices, not {index!r}",
                hints=("Pass whole-number cell indices, counted from 0.",),
            )
    return None


def _export_format(params: Mapping[str, Any]) -> str:
    """The format an ``export`` call names, from ``format`` or the path's extension.

    One spelling for the handler and mock mode: the handler dispatches on it, and the
    validators judge it, so it has to mean the same thing on both sides.
    """
    fmt = params.get("format")
    if fmt:
        return str(fmt).lower()
    path = str(params.get("file_path") or "")
    return os.path.splitext(path)[1].lstrip(".").lower()


def export_target_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an ``export`` call with no usable format earns, or None.

    Two sentences, because they answer different mistakes.  A call that names nothing
    (``format`` empty, no ``file_path``) is told what to pass; a call that names a
    format the tool cannot write keeps the sentence the handler used to raise, which
    the plan freezes (D2).

    ``format`` is a schema enum, so the gate answers a mistyped one; a ``file_path``
    whose extension names no export is the one route around the enum, and without this
    check it would fall through to the F3D branch with ``obj`` in hand.
    """
    fmt = _export_format(params)
    if fmt in EXPORT_FORMATS:
        return None
    if fmt:
        message = f"Unknown format: {fmt}. Expected: stl, step, f3d"
    else:
        message = "Specify format (stl/step/f3d) or file_path with extension"
    return _hints.Refusal(
        "INVALID_INPUT",
        message,
        hints=(
            "Pass format='stl', 'step' or 'f3d', or a file_path that ends in one "
            "of those.",
        ),
    )


def export_body_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal an STL or STEP export without a body earns, or None.

    F3D exports the document, so it needs no body; the two messages differ only in
    the format they name, and are kept verbatim, which is why one validator answers
    both.
    """
    if params.get("body_name"):
        return None
    fmt = _export_format(params)
    if fmt == "stl":
        message = "body_name required for STL export"
    elif fmt in ("step", "stp"):
        message = "body_name required for STEP export"
    else:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        message,
        hints=("Pass body_name naming the body to export.",),
    )


def cam_target_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a ``cam_generate_toolpath`` with nothing to generate earns, or None.

    ``operation_name`` alone is enough: the handler searches every setup for it,
    refuses a name held by more than one, and the narrowed search refuses a name held
    twice inside a setup as well.  Judged before the CAM product is looked up: the
    caller can fix this call without Fusion, and the add-in's other parameter checks
    come first too.
    """
    if (
        params.get("generate_all")
        or params.get("setup_name")
        or params.get("operation_name")
    ):
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "Provide setup_name, operation_name, or generate_all=true",
        hints=(
            "Pass operation_name to generate that one operation, or setup_name "
            "for all of that setup's.",
            "generate_all=true generates every setup's toolpaths.",
        ),
    )


def symmetry_line_refusal(params: Mapping[str, Any]) -> _hints.Refusal | None:
    """The refusal a ``symmetry`` constraint with no mirror line earns, or None.

    ``symmetry`` is the one constraint type built from three entities: the two that
    are mirrored and the line they are mirrored about.  The line is its own
    parameter, so a call without it is short an argument — judged here, before a
    sketch is read, so mock mode (which has no sketch) answers it too.  Whether the
    index names a line needs Fusion; that one was given does not.
    """
    if params.get("constraint_type") != "symmetry":
        return None
    if params.get("symmetry_line") is not None:
        return None
    return _hints.Refusal(
        "INVALID_INPUT",
        "symmetry needs symmetry_line — the index of the sketch line the two "
        "entities are mirrored about",
        hints=("Pass symmetry_line: the index of a sketch line to mirror about.",),
    )


def sketch_plane_z_note() -> str:
    """What the caller is told when a ``z`` was projected away onto the sketch plane.

    A success note, never a refusal: the geometry exists, in the sketch plane, and the
    note is the only thing that says the ``z`` did not move it.  Mock mode reports it
    too, so it is one sentence rather than two copies of one.
    """
    return (
        "Sketch curves lie in the sketch plane, so the z component was "
        "dropped instead of being added to the plane's own offset. "
        "Use create_sketch(z_offset=...) to move the plane itself."
    )
