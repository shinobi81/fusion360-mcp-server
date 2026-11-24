"""
CAM commands: the Manufacture product, its setups, operations and toolpaths.

The commands and the helpers only they call.  A helper a second domain needs lives
in ``handler_base``; this module imports nothing from another domain and nothing
from ``command_handler``.  Mixed into ``command_handler.CommandHandler``.

Every command here resolves the CAM product through ``_get_cam`` first: on current
Fusion builds it is only instantiated once the Manufacture workspace has been
activated for the document, so the lookup activates it on demand.
"""


import os
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from . import cam_tool as _cam_tool
from . import fusion_api as adsk
from . import get_logger
from . import hints as _hints
from . import parameter_units as _param_units
from . import rules as _rules

log = get_logger("handler")

# The advice a name-based refusal gives: ``cam_list_operations`` needs a setup, so
# the chain that reaches the real names starts at the setups.
_OPERATION_LIST_HINT = (
    "Call cam_list_setups, then cam_list_operations with a setup_name, to see the "
    "real names."
)

#: The advice a name the design holds twice earns.  Three commands resolve an operation
#: by name now, and one sentence for all three is what keeps their answers identical.
_AMBIGUOUS_OPERATION_HINT = (
    "There is no CAM rename tool; rename all but one with execute_code "
    "(operation.name = ...) so the name selects it."
)


def _ambiguous_operation_refusal(setup, name: str, count: int) -> "_hints.Refusal":
    """The refusal a name held *count* times in *setup* earns.

    A function rather than a literal at each site: ``cam_generate_toolpath``
    refuses this shape before it generates, and ``_find_operation`` refuses it for
    the commands that only read or post - one sentence, so the three agree.
    """
    return _hints.Refusal(
        "INVALID_INPUT",
        f"Setup '{setup.name}' holds {count} operations named '{name}'",
        hints=(_AMBIGUOUS_OPERATION_HINT,),
    )


def _and_list(names: list[str]) -> str:
    """``'A'``, ``'A' and 'B'``, ``'A', 'B' and 'C'`` for a hint's prose.

    A comma-join reads as a list, and a fixed verb after it produced "'A', 'B' holds
    one of them" - advice a caller has to parse twice.
    """
    quoted = [f"'{name}'" for name in names]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + f" and {quoted[-1]}"


if TYPE_CHECKING:  # pragma: no cover - the mixin's contract, for type checkers only
    # Not inherited at runtime: ``CommandHandler`` supplies the base.  The reason this
    # exists at all is stated once, above ``class HandlerBase``.
    from .handler_base import HandlerBase as _Contract
else:  # pragma: no cover - unchanged runtime hierarchy: ``object``
    _Contract = object


class CamCommands(_Contract):

    def _get_cam(self):
        """Get the CAM product from the active document.

        On recent Fusion builds the CAM product is only instantiated once
        the Manufacture workspace has been activated for the document, so
        activate it on demand instead of failing outright.  Note:
        itemByProductType *raises* when the product doesn't exist yet.
        """
        doc = self.app.activeDocument

        def _find_cam_product():
            try:
                return doc.products.itemByProductType("CAMProductType")
            except Exception:
                return None

        cam_product = _find_cam_product()
        if cam_product is None:
            ws = self.ui.workspaces.itemById("CAMEnvironment")
            if ws is not None:
                try:
                    ws.activate()
                    adsk.doEvents()
                except Exception as exc:
                    log.warning("Manufacture workspace activation failed: %s", exc)
                cam_product = _find_cam_product()

        if cam_product is None:
            raise _hints.Refusal(
                "WORKSPACE_UNAVAILABLE",
                "No CAM workspace found. Open the Manufacturing workspace "
                "in Fusion 360 at least once to initialise it.",
                hints=("Open the Manufacturing workspace once, then retry.",),
            )
        return cam_product

    def _find_setup(self, cam, name: str):
        for i in range(cam.setups.count):
            s = cam.setups.item(i)
            if s.name == name:
                return s
        raise RuntimeError(f"Setup '{name}' not found")

    def _find_operation(self, setup, name: str):
        """The one operation in *setup* named *name*.

        A name the setup holds twice is refused rather than resolved: the first-match
        scan this replaces posted the first of two from ``cam_post_process`` - writing
        G-code for an operation the caller had not named - and described the first of
        two from ``cam_get_operation_info``.
        """
        named = self._setup_operations_named(setup, name)
        if not named:
            raise RuntimeError(f"Operation '{name}' not found in setup '{setup.name}'")
        if len(named) > 1:
            raise _ambiguous_operation_refusal(setup, name, len(named))
        return named[0]

    def _setup_operations_named(self, setup, name: str):
        """Every operation in *setup* named *name*, in the tree's order."""
        named = []
        for i in range(setup.operations.count):
            operation = setup.operations.item(i)
            if operation.name == name:
                named.append(operation)
        return named

    def _operations_named(self, cam, name: str):
        """Every ``(setup, operation)`` pair named *name*, in the tree's order."""
        matches = []
        for i in range(cam.setups.count):
            setup = cam.setups.item(i)
            for operation in self._setup_operations_named(setup, name):
                matches.append((setup, operation))
        return matches

    def cam_list_setups(self):
        cam = self._get_cam()
        result = []
        for i in range(cam.setups.count):
            setup = cam.setups.item(i)
            ops = []
            for j in range(setup.operations.count):
                ops.append(setup.operations.item(j).name)
            result.append(
                {
                    "name": setup.name,
                    "operations": ops,
                    "is_valid": setup.isValid,
                }
            )
        return {"setups": result, "count": len(result)}

    def cam_list_operations(self, setup_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        result = []
        for i in range(setup.operations.count):
            op = setup.operations.item(i)
            result.append(
                {
                    "name": op.name,
                    "has_toolpath": op.hasToolpath,
                    "is_valid": op.isValid,
                }
            )
        return {"setup": setup_name, "operations": result, "count": len(result)}

    def cam_get_operation_info(self, setup_name: str, operation_name: str):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)
        op = self._find_operation(setup, operation_name)

        info = {
            "name": op.name,
            "is_valid": op.isValid,
            "has_toolpath": op.hasToolpath,
        }

        if hasattr(op, "tool") and op.tool:
            tool = op.tool
            desc = tool.description if hasattr(tool, "description") else str(tool)
            info["tool"] = {"description": desc}

        if hasattr(op, "parameters"):
            params = {}
            for param in op.parameters:
                with suppress(Exception):
                    params[param.name] = param.expression
            info["parameters"] = params

        return info

    def cam_create_setup(
        self,
        body_name: str,
        name: str | None = None,
        operation_type: str = "milling",
        stock_mode: str = "relative_box",
        stock_offset_sides: float = 0,
        stock_offset_top: float = 0,
        stock_offset_bottom: float = 0,
    ):
        # Judged before any object exists: the refusal's hint says nothing was
        # written, so a setup must not already be in the tree when it fires.
        stock_offset_sides = _param_units.require_finite(stock_offset_sides)
        stock_offset_top = _param_units.require_finite(stock_offset_top)
        stock_offset_bottom = _param_units.require_finite(stock_offset_bottom)
        # Judged here, before the CAM product is touched: an unknown mode used to be
        # passed through to Fusion, which refuses it and left a setup behind with no
        # stock applied.
        if stock_refusal := _rules.cam_stock_mode_refusal({"stock_mode": stock_mode}):
            raise stock_refusal

        cam = self._get_cam()
        body = self._body_by_name(body_name)

        op_type_map = {
            "milling": adsk.cam.OperationTypes.MillingOperation,
            "turning": adsk.cam.OperationTypes.TurningOperation,
            "cutting": adsk.cam.OperationTypes.JetOperation,
        }
        op_type = op_type_map.get(operation_type)
        if op_type is None:
            raise RuntimeError(
                f"Unknown operation_type '{operation_type}' "
                "— use milling/turning/cutting"
            )

        setup_input = cam.setups.createInput(op_type)
        setup_input.models = [body]

        if name:
            setup_input.name = name

        setup = cam.setups.add(setup_input)

        # Stock parameters live on the created setup, not the input. The vocabulary and
        # the ids are `rules.CAM_STOCK_MODES` - one table, measured on 2706.1.17, shared
        # with the schema and with mock mode.
        applied_stock: dict[str, Any] = {}
        failed_stock: dict[str, Any] = {}
        mode_id = _rules.CAM_STOCK_MODES[stock_mode]
        if self._set_cam_parameter(setup, "job_stockMode", mode_id, by_string=True):
            applied_stock["stock_mode"] = mode_id
        else:
            failed_stock["stock_mode"] = mode_id
        for param_name, value in (
            ("job_stockOffset", stock_offset_sides),
            ("job_stockOffsetTop", stock_offset_top),
            ("job_stockOffsetBottom", stock_offset_bottom),
        ):
            if value:
                if self._set_cam_parameter(setup, param_name, value):
                    applied_stock[param_name] = value
                else:
                    failed_stock[param_name] = value

        result = {
            "name": setup.name,
            "body": body_name,
            "operation_type": operation_type,
        }
        if applied_stock:
            result["stock_applied"] = applied_stock
        if failed_stock:
            result["stock_failed"] = failed_stock
            result["warning"] = (
                "Some stock parameters could not be applied — parameter "
                "names vary by Fusion build; inspect via cam_get_operation_info"
            )
        return result

    @staticmethod
    def _set_cam_parameter(target, param_name, value, by_string=False):
        """Set a CAM parameter on a setup or operation. Returns success.

        Raises ``ValueError`` for a non-finite numeric value — that is a bad
        argument, not an unavailable parameter name, and the two callers would
        otherwise report it as the latter.

        CAMParameter.value is read-only on current Fusion builds — values
        must be assigned via the ``expression`` property.  Enum parameters
        (e.g. tool_coolant) take quoted lowercase strings ('flood').
        """
        # Judged outside the try so a bad value classifies as INVALID_INPUT instead
        # of being reported as False - which both callers read as "that parameter
        # name is unavailable" and would answer by retrying the same value.
        value = _param_units.require_finite(value)
        try:
            params = getattr(target, "parameters", None)
            if params is None:
                return False
            p = params.itemByName(param_name)
            if p is None:
                return False
            p.expression = f"'{value}'" if by_string else str(value)
            return True
        except Exception as exc:
            log.debug("CAM parameter %s=%r failed: %s", param_name, value, exc)
            return False

    def _attach_tool(self, op, tool_payload: str) -> dict[str, Any]:
        """Give *op* the tool *tool_payload* defines, and describe it.

        Measured on Fusion 2706.1.17: ``Tool.createFromJson`` accepts a complete tool
        object, ``Operation.tool`` takes the result, and Fusion registers it in
        ``documentToolLibrary`` itself - the operation then generates its toolpath.
        Only the flat end mill has been measured end to end, which is why the payload
        comes from ``cam_tool`` rather than being assembled at this call site.

        A refusal here removes the operation, the promise the geometry seam keeps too:
        a retry must not leave a second half-built operation in the setup.

        The two calls are guarded apart because they fail for different reasons: a
        ``RuntimeError`` from ``createFromJson`` is Fusion judging the JSON, while an
        ``AttributeError`` from the *assignment* is a build where ``Operation.tool`` is
        not settable - a defect of ours that the caller cannot fix by resending the
        same payload. One shared message would blame the wrong one.
        """

        def remove_operation() -> None:
            """Take the operation out again, never masking the refusal being raised.

            ``deleteMe`` is measured to work on 2706.1.17, but if it ever refuses, its
            exception would replace a classified refusal with ``UNKNOWN`` and no hints -
            the shape #138 removed.
            """
            with suppress(Exception):
                op.deleteMe()

        try:
            tool = adsk.cam.Tool.createFromJson(tool_payload)
        except AttributeError as exc:
            # ``adsk.cam.Tool`` missing is this environment, not the caller's JSON.
            remove_operation()
            raise _hints.Refusal(
                "INTERNAL_ERROR",
                f"This Fusion build has no usable Tool.createFromJson: {exc}. "
                "The operation was removed.",
                hints=("This is an add-in defect, not an input problem.",),
            ) from exc
        except Exception as exc:
            remove_operation()
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Fusion refused the tool definition: {exc}. The operation was "
                "removed.",
                hints=(
                    "Pass tool_diameter for the one measured tool shape, or a "
                    "complete tool_json taken from a Fusion tool library.",
                ),
            ) from exc
        try:
            op.tool = tool
        except AttributeError as exc:
            remove_operation()
            raise _hints.Refusal(
                "INTERNAL_ERROR",
                f"This Fusion build does not take a tool on an operation: {exc}. "
                "The operation was removed.",
                hints=("This is an add-in defect, not an input problem.",),
            ) from exc
        except Exception as exc:
            remove_operation()
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Fusion refused the tool on the operation: {exc}. The operation "
                "was removed.",
            ) from exc
        # A read-back after a successful attach: nothing depends on it, so a build that
        # will not answer costs the description and not the operation.
        description = None
        with suppress(Exception):
            description = getattr(op.tool, "description", None)
        return {"description": description} if description else {}

    @staticmethod
    def _all_operations(cam) -> list:
        """Every operation the CAM product holds, in the tree's order.

        ``generateAllToolpaths`` takes no target, so this is how a generation failure
        gets attributed to the operation Fusion recorded it on: ``_wait_future`` names
        that operation in the refusal rather than answering one sentence for N of them.
        """
        operations = []
        for i in range(cam.setups.count):
            setup = cam.setups.item(i)
            for j in range(setup.operations.count):
                operations.append(setup.operations.item(j))
        return operations

    def _select_operation_geometry(self, op, faces: list) -> str:
        """Apply a face selection to the operation's own geometry parameter.

        The parameter name is strategy-dependent and only Fusion knows it - measured on
        2706.1.17: ``contours`` for ``contour2d``, ``pockets`` for ``pocket2d`` and
        ``adaptive2d``, ``machiningBoundarySel`` for ``adaptive`` and
        ``pocket_clearing`` - so it is discovered rather than assumed: the one
        CAD-contour value that is not the stock boundary.  ``FaceContourSelection`` was
        measured to be accepted by all five of those parameters.

        Reaching the discovery failure means the measurement moved under us, and the
        operation is removed again rather than left half-configured; the strategy is
        read *before* the delete, because a deleted Fusion object may refuse reads.
        """
        parameter = next(
            (
                candidate
                for candidate in op.parameters
                if candidate.name != "stockContours"
                and hasattr(candidate.value, "applyCurveSelections")
            ),
            None,
        )
        if parameter is None:
            strategy = op.strategy
            op.deleteMe()
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Strategy '{strategy}' exposed no geometry parameter on this Fusion "
                "build; the operation was removed again",
                hints=(
                    "Use a strategy measured to carry one; cam_create_operation's "
                    "schema lists them.",
                ),
            )

        try:
            selections = parameter.value.getCurveSelections()
            selections.clear()
            selection = selections.createNewFaceContourSelection()
            selection.inputGeometry = list(faces)
            parameter.value.applyCurveSelections(selections)
        except AttributeError as exc:
            # An invented method name is an add-in defect.  Left to propagate it would
            # reach a caller as ``UNKNOWN`` with no hints - the shape #138 removed - and
            # the generic branch below would blame the caller's faces.  The operation
            # goes for the same reason as there: the parameter may already be emptied.
            strategy = op.strategy
            op.deleteMe()
            raise _hints.Refusal(
                "INTERNAL_ERROR",
                f"Strategy '{strategy}' face selection called an API this Fusion "
                f"build does not have: {exc}. The operation was removed.",
                hints=(
                    "This is an add-in defect, not an input problem.",
                    # `check_fusion_api.py` walks `adsk.<dotted.path>` names only; this
                    # failure is a method or property miss on an object Fusion returned,
                    # so the hint names the binding rather than promising the audit sees
                    # it.  The defect kind's own advice in ``hints.py`` is the same rule
                    # for the module-shaped case.
                    "Read the call against the shipped binding; "
                    "`scripts/check_fusion_api.py` covers `adsk.<name>`, not methods.",
                ),
            ) from exc
        except Exception as exc:
            # The parameter is emptied before the selection is applied, so a refusal
            # here would leave the operation with geometry it no longer has.  Nothing
            # measured says these three calls refuse; the guard is what keeps the
            # "no refusal leaves a half-built operation" promise true either way.
            strategy = op.strategy
            op.deleteMe()
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Fusion refused the face selection for strategy '{strategy}': "
                f"{exc}. The operation was removed.",
                hints=("Check the faces belong to the setup's model, then retry.",),
            ) from exc
        return parameter.name

    def cam_create_operation(
        self,
        setup_name: str,
        strategy: str,
        name: str | None = None,
        tool_number: int | None = None,
        tool_diameter: float | None = None,
        tool_length: float | None = None,
        tool_flutes: int | None = None,
        tool_json: str | None = None,
        stepdown: float | None = None,
        stepover: float | None = None,
        feed_rate: float | None = None,
        spindle_speed: float | None = None,
        coolant: str = "flood",
        body_name: str | None = None,
        face_indices: list[int] | None = None,
    ):
        # Judged before the operation is created, so a refusal's hint ("nothing
        # was written") stays true: a bad value is not an unavailable name.
        for _numeric in (
            tool_number,
            tool_diameter,
            tool_length,
            tool_flutes,
            stepdown,
            stepover,
            feed_rate,
            spindle_speed,
        ):
            _param_units.require_finite(_numeric)

        if strategy_refusal := _rules.cam_strategy_refusal({"strategy": strategy}):
            raise strategy_refusal
        if geometry_refusal := _rules.cam_geometry_refusal(
            {
                "strategy": strategy,
                "body_name": body_name,
                "face_indices": face_indices,
            }
        ):
            raise geometry_refusal
        if tool_refusal := _rules.cam_tool_refusal(
            {
                "tool_json": tool_json,
                "tool_diameter": tool_diameter,
                "tool_length": tool_length,
                "tool_flutes": tool_flutes,
                "tool_number": tool_number,
            }
        ):
            raise tool_refusal

        # Built before the operation exists, so a value that cannot become a tool
        # refuses without leaving one behind.  Its JSON is only ever the complete
        # shape: a partial one crashed Fusion 2706.1.17 (see ``cam_tool``).
        tool_payload = tool_json
        if tool_payload is None and tool_diameter is not None:
            # Raises a typed refusal for a value that cannot be a tool, and does it
            # before the operation exists, so a bad argument leaves nothing behind.
            tool_payload = _cam_tool.build_tool_json(
                tool_diameter=tool_diameter,
                tool_length=tool_length,
                tool_flutes=(
                    tool_flutes if tool_flutes is not None else _cam_tool.DEFAULT_FLUTES
                ),
                tool_number=tool_number if tool_number is not None else 1,
            )

        # Everything a face selection needs is judged before the operation exists, so
        # no refusal here can leave a half-built one behind: the body must resolve and
        # every index must be in range against it.
        selection_faces = None
        if face_indices:
            body = self._body_by_name(body_name)
            out_of_range = [
                index for index in face_indices if not (0 <= index < body.faces.count)
            ]
            if out_of_range:
                raise _hints.Refusal(
                    "INVALID_INPUT",
                    f"Face index {out_of_range[0]} is out of range for body "
                    f"'{body.name}' ({body.faces.count} faces)",
                    hints=(
                        "Enumerate with execute_code (`body.faces.item(i)`) - no "
                        "tool lists faces yet.",
                    ),
                )
            selection_faces = [body.faces.item(index) for index in face_indices]

        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        op_input = setup.operations.createInput(strategy)
        if name:
            op_input.name = name

        op = setup.operations.add(op_input)
        if op is None:
            raise _hints.Refusal(
                "FUSION_REFUSED",
                f"Fusion rejected strategy '{strategy}' for setup '{setup_name}'",
                hints=(
                    "Check the strategy name against cam_create_operation's schema.",
                ),
            )

        # Operation parameters (stepdown, feeds, speeds...) only exist on
        # the created operation, keyed by strategy-dependent names.
        applied = {}
        failed = {}
        for param_name, value, by_string in (
            ("maximumStepdown", stepdown, False),
            ("maximumStepover", stepover, False),
            ("tool_feedCutting", feed_rate, False),
            ("tool_spindleSpeed", spindle_speed, False),
            ("tool_coolant", coolant, True),
        ):
            if value is None:
                continue
            if self._set_cam_parameter(op, param_name, value, by_string):
                applied[param_name] = value
            else:
                failed[param_name] = value

        result = {"name": op.name, "setup": setup_name, "strategy": strategy}
        # The geometry seam runs before the tool goes on, because it is the only step
        # here that removes the operation after it exists - and attaching a tool
        # registers it in ``documentToolLibrary`` (measured on 2706.1.17). The other
        # order would leave a tool entry behind on every refused retry, while the
        # refusal promises only that "the operation was removed".
        if selection_faces is not None:
            result["geometry"] = {
                "parameter": self._select_operation_geometry(op, selection_faces),
                "face_indices": list(face_indices or []),
            }
        if tool_payload is not None:
            result["tool"] = self._attach_tool(op, tool_payload)
            if tool_diameter is not None:
                result["tool"]["diameter_cm"] = tool_diameter
        else:
            # A reply rather than a refusal: the operation is usable and a tool can
            # arrive later.  Generation, however, will not: Fusion answers this exact
            # sentence (measured on 2706.1.17), so the reply says so now rather than
            # leaving it to a 25 s wait after the caller's next call.
            result["tool"] = None
            result["tool_warning"] = _rules.CAM_NO_TOOL_WARNING
        if applied:
            result["parameters_applied"] = applied
        if failed:
            result["parameters_failed"] = failed
            result["warning"] = (
                "Some parameters are not available for this strategy — "
                "check available names via cam_get_operation_info"
            )
        return result

    def cam_generate_toolpath(
        self,
        setup_name: str | None = None,
        operation_name: str | None = None,
        generate_all: bool = False,
    ):
        # Judged before the CAM product is looked up: the caller can fix this call
        # without it, and the message names the arguments that would work.
        if refusal := _rules.cam_target_refusal(
            {
                "setup_name": setup_name,
                "operation_name": operation_name,
                "generate_all": generate_all,
            }
        ):
            raise refusal

        cam = self._get_cam()

        if generate_all:
            targets = self._all_operations(cam)
            # The verdicts Fusion already holds, taken before generating: only a change
            # from these is this call's failure.
            prior = self._operation_errors(targets)
            future = cam.generateAllToolpaths(False)
            self._wait_future(future, operations=targets, prior_errors=prior)
            return {"generated": True, "scope": "all"}

        if operation_name and not setup_name:
            matches = self._operations_named(cam, operation_name)
            if not matches:
                raise _hints.Refusal(
                    "NAME_NOT_FOUND",
                    f"Operation '{operation_name}' not found in any setup",
                    hints=(_OPERATION_LIST_HINT,),
                )
            if len(matches) > 1:
                # How many matches each setup holds: ``setup_name`` only narrows the
                # search, so it is advice only for the setups holding exactly one.
                counts: dict[str, int] = {}
                for setup, _operation in matches:
                    counts[setup.name] = counts.get(setup.name, 0) + 1
                setup_names = list(counts)
                # Assigning an operation a name already taken *inside its setup* is
                # suffixed by Fusion (measured live: renaming Face11 to Face10 produced
                # Face101), so a rename cannot leave two matches in one setup. The
                # narrowed branch below stays as the guard for the create path, which
                # no measurement rules out.
                hints = [
                    "There is no CAM rename tool; rename the duplicates with "
                    "execute_code (operation.name = ...) so the name selects one."
                ]
                resolvable = [name for name, count in counts.items() if count == 1]
                ambiguous = [name for name, count in counts.items() if count > 1]
                if len(counts) > 1:
                    if not ambiguous:
                        hints.insert(
                            0, "Pass setup_name to choose which setup to generate."
                        )
                    elif resolvable:
                        one_each = (
                            "it holds one match"
                            if len(resolvable) == 1
                            else "they hold one match each"
                        )
                        verb = "holds" if len(ambiguous) == 1 else "hold"
                        hints.insert(
                            0,
                            f"Pass setup_name with {_and_list(resolvable)}: "
                            f"{one_each}, while {_and_list(ambiguous)} {verb} more "
                            "than one, so narrowing there cannot help.",
                        )
                raise _hints.Refusal(
                    "INVALID_INPUT",
                    f"Operation '{operation_name}' matches {len(matches)} "
                    f"operations in: {', '.join(setup_names)}",
                    hints=tuple(hints),
                )
            setup, operation = matches[0]
            prior = self._operation_errors((operation,))
            future = cam.generateToolpath(operation)
            self._wait_future(future, operations=(operation,), prior_errors=prior)
            return {
                "generated": True,
                "scope": "operation",
                "setup": setup.name,
                "operation": operation_name,
            }

        if operation_name and setup_name:
            setup = self._find_setup(cam, setup_name)
            named = self._setup_operations_named(setup, operation_name)
            if not named:
                raise _hints.Refusal(
                    "NAME_NOT_FOUND",
                    f"Operation '{operation_name}' not found in setup '{setup.name}'",
                    hints=(_OPERATION_LIST_HINT,),
                )
            if len(named) > 1:
                raise _ambiguous_operation_refusal(
                    setup, operation_name, len(named)
                )
            prior = self._operation_errors((named[0],))
            future = cam.generateToolpath(named[0])
            self._wait_future(future, operations=(named[0],), prior_errors=prior)
            return {
                "generated": True,
                "scope": "operation",
                "setup": setup.name,
                "operation": operation_name,
            }

        if setup_name:
            setup = self._find_setup(cam, setup_name)
            generated = [
                setup.operations.item(i) for i in range(setup.operations.count)
            ]
            ops = adsk.core.ObjectCollection.create()
            for operation in generated:
                ops.add(operation)
            prior = self._operation_errors(generated)
            future = cam.generateToolpath(ops)
            self._wait_future(future, operations=generated, prior_errors=prior)
            return {"generated": True, "scope": "setup", "setup": setup_name}

    def _resolve_post(self, path: str) -> str:
        """The ``.cps`` file a ``post_processor`` names, or a refusal naming *path*.

        A full path (or anything ending in ``.cps``) is taken as given; a short name
        is resolved against the build's own post folder, which current builds do not
        provide - posts are cloud-library based.

        Split out of ``cam_post_process`` so the refusal is reachable without a CAM
        ``Product``: a missing file is the caller's path, not the design or the build.
        """
        if path.endswith(".cps") or os.path.sep in path:
            post_config = path
        else:
            cam = self._get_cam()
            post_folder = getattr(cam, "genericPostFolder", None)
            if not post_folder:
                raise _hints.Refusal(
                    "FUSION_REFUSED",
                    "This Fusion build has no local generic post folder "
                    "(posts are cloud-library based). Pass the full path to "
                    "the .cps file in 'post_processor' instead of a short "
                    "name.",
                    hints=("Pass the full path to a .cps file in post_processor.",),
                )
            post_config = os.path.join(post_folder, f"{path}.cps")

        if not os.path.isfile(post_config):
            raise _hints.Refusal(
                "INVALID_INPUT",
                f"Post processor not found: {post_config}",
                hints=("Pass a .cps path that exists on this machine.",),
            )
        return post_config

    def cam_post_process(
        self,
        setup_name: str,
        operation_name: str | None = None,
        post_processor: str = "fanuc",
        output_folder: str | None = None,
        output_units: str = "mm",
    ):
        cam = self._get_cam()
        setup = self._find_setup(cam, setup_name)

        if not output_folder:
            output_folder = os.path.join(os.path.expanduser("~"), "Desktop")

        post_config = self._resolve_post(post_processor)

        units = (
            adsk.cam.PostOutputUnitOptions.MillimetersOutput
            if output_units == "mm"
            else adsk.cam.PostOutputUnitOptions.InchesOutput
        )

        post_input = adsk.cam.PostProcessInput.create(
            setup_name, post_config, output_folder, units
        )
        post_input.isOpenInEditor = False

        if operation_name:
            op = self._find_operation(setup, operation_name)
            cam.postProcess(op, post_input)
        else:
            cam.postProcess(setup, post_input)

        return {
            "setup": setup_name,
            "post_processor": post_processor,
            "output_folder": output_folder,
            "units": output_units,
        }
