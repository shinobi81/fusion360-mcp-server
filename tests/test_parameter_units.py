"""Tests for user-parameter units.

``createByReal()`` is read in Fusion's internal units -- centimetres for a
length, radians for an angle -- so handing it a value the caller meant as
millimetres inflates it tenfold while the parameter still reads "mm". The
rules live in ``addon/server/parameter_units.py``, which imports no ``adsk``
and is loaded here by path.

The two call sites into Fusion's API are covered by running the handler against
the fake runtime, so a handler that rebuilt the choice inline fails here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from addon.server.hints import classify
from fusion360_mcp.mock import mock_command
from tests.fakes.design import FakeDesign
from tests.fakes.runtime import FakeValueInput

ADDON_SERVER = Path(__file__).resolve().parent.parent / "addon" / "server"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parameter_units = _load(ADDON_SERVER / "parameter_units.py", "parameter_units")


class TestExpressionFor:
    @pytest.mark.parametrize(
        ("value", "unit", "expected"),
        [
            (1000, "mm", "1000 mm"),
            (1200, "mm", "1200 mm"),
            (2.5, "cm", "2.5 cm"),
            (90, "deg", "90 deg"),
            (1, "in", "1 in"),
        ],
    )
    def test_the_requested_unit_reaches_the_expression(self, value, unit, expected):
        # The unit must survive into the expression -- writing the value
        # against a fixed unit, or dropping it, is the bug being fixed.
        assert parameter_units.expression_for(value, unit) == expected

    @pytest.mark.parametrize("unit", ["", "   ", None])
    def test_a_unitless_parameter_keeps_the_bare_number(self, unit):
        assert parameter_units.expression_for(7, unit) == "7"

    def test_surrounding_whitespace_is_trimmed(self):
        assert parameter_units.expression_for(5, "  mm  ") == "5 mm"


class TestNeedsExpression:
    @pytest.mark.parametrize("unit", ["mm", "deg", " in "])
    def test_a_unit_requires_the_string_form(self, unit):
        assert parameter_units.needs_expression(unit)

    @pytest.mark.parametrize("unit", ["", "   ", None])
    def test_unitless_does_not(self, unit):
        assert not parameter_units.needs_expression(unit)


class TestNormaliseUnit:
    @pytest.mark.parametrize(
        ("given", "expected"), [("mm", "mm"), (" mm ", "mm"), (None, ""), ("", "")]
    )
    def test_normalisation(self, given, expected):
        assert parameter_units.normalise_unit(given) == expected


class TestBuildValueInput:
    """The choice between the two factories is the thing that was wrong."""

    @staticmethod
    def _factories():
        calls = []
        return (
            calls,
            lambda s: calls.append(("string", s)),
            lambda v: calls.append(("real", v)),
        )

    @pytest.mark.parametrize(
        ("value", "unit", "expected"),
        [(1000, "mm", "1000 mm"), (90, "deg", "90 deg"), (2.5, "in", "2.5 in")],
    )
    def test_a_unit_goes_through_the_string_factory(self, value, unit, expected):
        calls, from_string, from_real = self._factories()
        parameter_units.build_value_input(value, unit, from_string, from_real)
        assert calls == [("string", expected)]

    @pytest.mark.parametrize("unit", ["", "   ", None])
    def test_unitless_goes_through_the_real_factory(self, unit):
        calls, from_string, from_real = self._factories()
        parameter_units.build_value_input(7, unit, from_string, from_real)
        assert calls == [("real", 7)]

    def test_centimetres_still_carry_their_unit(self):
        # cm happens to match Fusion's internal unit, so a bare real would
        # look correct here -- it must still take the explicit path.
        calls, from_string, from_real = self._factories()
        parameter_units.build_value_input(3, "cm", from_string, from_real)
        assert calls == [("string", "3 cm")]

    @pytest.mark.parametrize("unit", ["", "   ", None])
    def test_a_unitless_value_too_large_for_a_real_is_written_as_text(self, unit):
        """A 401-digit JSON integer is finite but not representable as a double.

        ``createByReal`` cannot carry it, and the OverflowError it raises matches
        no hints rule, so the caller saw ``UNKNOWN`` with no hints.  The rule is
        already written next door: ``value_input_for`` sends such an integer to
        the expression form, because Fusion should judge the magnitude.
        """
        huge = 10**400
        calls, from_string, from_real = self._factories()
        parameter_units.build_value_input(huge, unit, from_string, from_real)
        assert calls == [("string", str(huge))]

    @pytest.mark.parametrize("unit", ["", None])
    def test_a_unitless_expression_is_passed_through_as_text(self, unit):
        """A unitless parameter may be handed an expression, not only a number.

        ``create_parameter(value="boxL")`` is legal, and ``createByReal`` would
        refuse the string; it took that path until the real-or-expression
        decision moved here.  Pinned so the next change to this function cannot
        quietly route text into a factory that cannot carry it.
        """
        calls, from_string, from_real = self._factories()
        parameter_units.build_value_input("boxL", unit, from_string, from_real)
        assert calls == [("string", "boxL")]


class TestRequireFinite:
    """A non-finite value has to be refused before it reaches Fusion.

    ``json.loads`` accepts the non-standard ``Infinity`` and ``NaN`` literals,
    so a socket client can deliver one; written through, it becomes the
    expression ``"inf mm"``, which Fusion rejects as an opaque API error.
    """

    @pytest.mark.parametrize(
        ("value", "rendered"),
        [
            (float("inf"), "inf"),
            (float("-inf"), "-inf"),
            (float("nan"), "nan"),
        ],
    )
    def test_a_non_finite_value_is_refused(self, value, rendered):
        with pytest.raises(ValueError, match="invalid parameter value") as exc_info:
            parameter_units.require_finite(value)
        # The message has to name the offending value and the reason.
        assert rendered in str(exc_info.value)
        assert "is not finite" in str(exc_info.value)

    @pytest.mark.parametrize("value", [2.5, 0, -7, 1e300])
    def test_a_finite_value_passes_through_unchanged(self, value):
        assert parameter_units.require_finite(value) == value

    def test_the_refusal_classifies_as_invalid_input(self):
        with pytest.raises(ValueError) as exc_info:
            parameter_units.require_finite(float("nan"))
        assert classify(str(exc_info.value))[0] == "INVALID_INPUT"

    def test_the_refusal_points_at_the_value_not_the_units(self):
        """The hints are the repair channel; the generic ones would mislead.

        ``INVALID_INPUT``'s general text blames units and enums, but Fusion
        never saw this value -- so the finiteness rule has to supply its own.
        """
        with pytest.raises(ValueError) as exc_info:
            parameter_units.require_finite(float("inf"))

        kind, hints = classify(str(exc_info.value))

        assert kind == "INVALID_INPUT"
        assert hints, "the finiteness rule must supply its own hints"
        assert any("finite" in hint.lower() for hint in hints)
        # Not the units/enum wording: units have nothing to do with an infinity.
        assert not any("unit" in hint.lower() for hint in hints)
        assert not any("cm" in hint for hint in hints)


class TestNonFiniteCallSites:
    """Both handlers refuse the value, and leave the design untouched."""

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_create_parameter_refuses_a_non_finite_value(self, bound_handler, value):
        design = FakeDesign(features=0)

        handler = bound_handler(design)
        with pytest.raises(ValueError, match="invalid parameter value"):
            handler.create_parameter(name="length", value=value, unit="mm")

        # Nothing may be added: a rejected value must not leave "inf mm" behind.
        assert design.userParameters.count == 0
        assert design.userParameters.itemByName("length") is None

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_set_parameter_refuses_a_non_finite_value(self, bound_handler, value):
        design = FakeDesign(features=0)
        stored = design.userParameters.add(
            "angle", FakeValueInput("90 deg", "string"), "deg", ""
        )

        with pytest.raises(ValueError, match="invalid parameter value"):
            bound_handler(design).set_parameter("angle", value)

        assert stored.expression == "90 deg"

    def test_set_parameter_judges_the_value_before_the_name(self, bound_handler):
        # Same order as create_parameter: a bad argument outranks a name that
        # does not exist, so the message names the real problem.
        design = FakeDesign(features=0)

        with pytest.raises(ValueError, match="invalid parameter value"):
            bound_handler(design).set_parameter("no_such_parameter", float("inf"))


class TestNonNumberValues:
    """A value that is not a number is not this guard's business.

    ``math.isfinite`` raises ``TypeError`` on a string, and no hints rule
    matches that, so judging one would report ``UNKNOWN`` with no hints. Both
    handlers used to accept one: ``create_parameter(value="2.5")`` reached
    Fusion as ``createByString("2.5 mm")`` and ``set_parameter`` writes the
    same text into the parameter's own unit. Fusion's API does the type
    checking, and the tool schema declares ``value`` as a number, so a
    non-number is the caller's problem -- not a finiteness failure.
    """

    def test_require_finite_passes_a_non_number_through(self):
        assert parameter_units.require_finite("2.5") == "2.5"

    def test_create_parameter_still_takes_the_value_as_text(self, bound_handler):
        design = FakeDesign(features=0)

        result = bound_handler(design).create_parameter(
            name="length", value="2.5", unit="mm"
        )

        assert result["expression"] == "2.5 mm"
        stored = design.userParameters.itemByName("length")
        assert stored is not None
        assert stored.source == "string"

    def test_set_parameter_still_writes_the_value_as_text(self, bound_handler):
        design = FakeDesign(features=0)
        stored = design.userParameters.add(
            "angle", FakeValueInput("90 deg", "string"), "deg", ""
        )

        bound_handler(design).set_parameter("angle", "45")

        assert stored.expression == "45 deg"

    def test_mock_mode_accepts_it_the_way_the_handler_does(self):
        # Mock mode leaves a non-number alone too; a mock that refused here
        # would be stricter than the add-in it advertises itself as matching.
        result = mock_command(
            "create_parameter", {"name": "length", "value": "2.5", "unit": "mm"}
        )

        assert result["ok"] is True
        assert result["expression"] == "2.5 mm"


class TestTheRefusalIsTheSameOnBothSides:
    """Mock mode promises to report what the add-in would report.

    The refusal text lives twice -- ``parameter_units.require_finite`` raises
    it, ``mock._non_finite_error`` returns it -- and mock mode is what a caller
    without Fusion develops against. Pinned as an equality because reviewing
    two similar strings is not a test: an edit to one has to fail here.
    """

    @pytest.mark.parametrize(
        "value", [float("inf"), float("-inf"), float("nan")], ids=str
    )
    def test_create_parameter(self, bound_handler, value):
        with pytest.raises(ValueError) as exc_info:
            bound_handler(FakeDesign(features=0)).create_parameter(
                name="length", value=value, unit="mm"
            )

        result = mock_command(
            "create_parameter", {"name": "length", "value": value, "unit": "mm"}
        )

        assert result["ok"] is False
        assert result["error_message"] == str(exc_info.value)

    @pytest.mark.parametrize(
        "value", [float("inf"), float("-inf"), float("nan")], ids=str
    )
    def test_set_parameter(self, bound_handler, value):
        design = FakeDesign(features=0)
        design.userParameters.add(
            "angle", FakeValueInput("90 deg", "string"), "deg", ""
        )

        with pytest.raises(ValueError) as exc_info:
            bound_handler(design).set_parameter("angle", value)

        result = mock_command("set_parameter", {"name": "angle", "value": value})

        assert result["ok"] is False
        assert result["error_message"] == str(exc_info.value)


class TestCallSites:
    """Both call sites must go through this module, not rebuild the choice.

    The fake records which ``ValueInput`` factory produced the parameter, so an
    inline ``createByString(expression_for(...))`` — same text, wrong branch for
    a unitless value — is still caught: a united parameter must take
    ``createByString`` and a unitless one ``createByReal``.
    """

    def test_a_united_parameter_takes_the_string_factory(self, bound_handler):
        design = FakeDesign(features=0)

        bound_handler(design).create_parameter(name="length", value=1000, unit="mm")

        stored = design.userParameters.itemByName("length")
        assert stored is not None
        assert stored.expression == "1000 mm"
        assert stored.source == "string"

    def test_a_unitless_parameter_takes_the_real_factory(self, bound_handler):
        design = FakeDesign(features=0)

        bound_handler(design).create_parameter(name="count", value=7, unit="")

        stored = design.userParameters.itemByName("count")
        assert stored is not None
        assert stored.expression == "7"
        assert stored.source == "real"

    def test_set_parameter_writes_the_expression_not_the_value(self, bound_handler):
        design = FakeDesign(features=0)
        stored = design.userParameters.add(
            "angle", FakeValueInput("90 deg", "string"), "deg", ""
        )

        bound_handler(design).set_parameter("angle", 45)

        # A handler that hardcoded "mm" would pass on a length and fail here.
        assert stored.expression == "45 deg"


class TestMockContract:
    def test_create_parameter_reports_the_resulting_expression(self):
        result = mock_command(
            "create_parameter", {"name": "frame_length", "value": 1000, "unit": "mm"}
        )
        assert result["expression"] == "1000 mm"

    def test_create_parameter_trims_the_unit_like_the_addon(self):
        result = mock_command(
            "create_parameter", {"name": "padded", "value": 5, "unit": "  mm  "}
        )
        assert result["unit"] == "mm"
        assert result["expression"] == "5 mm"

    @pytest.mark.parametrize("unit", ["", "   "])
    def test_create_parameter_keeps_a_blank_unit_unitless(self, unit):
        # Blank means unitless in the addon; mock must not turn it into mm.
        result = mock_command(
            "create_parameter", {"name": "bare", "value": 7, "unit": unit}
        )
        assert result["unit"] == ""
        assert result["expression"] == "7"

    def test_set_parameter_does_not_invent_a_unit(self):
        # set_parameter takes no unit; mock mode holds no design, so it cannot
        # know what the target parameter declares.
        result = mock_command("set_parameter", {"name": "frame_length", "value": 1200})
        assert result["value"] == 1200
        assert result["unit"] is None
        assert result["expression"] is None


class TestOversizedIntegers:
    """An int is finite; converting a huge one to float is what used to fail."""

    def test_a_401_digit_int_is_accepted(self):
        # json.loads('1' + '0' * 400) yields exactly this shape, and
        # math.isfinite raises OverflowError converting it to float.
        huge = json.loads("1" + "0" * 400)
        assert parameter_units.require_finite(huge) == huge

    def test_a_normal_int_still_passes_through(self):
        assert parameter_units.require_finite(7) == 7

    def test_the_mock_accepts_the_same_huge_int(self):
        # The two mirrors are the contract (AGENTS.md): mock mode must not raise
        # where the add-in now succeeds, or --mode mock reports a failure that
        # the real call does not have.
        huge = json.loads("1" + "0" * 400)
        result = mock_command(
            "create_parameter", {"name": "w", "value": huge, "unit": "mm"}
        )
        assert result.get("ok") is True


class TestCamParameterRefusesNonFinite:
    """CAM parameter values reach Fusion as expressions, so inf/nan is refused."""

    class _Param:
        def __init__(self):
            self.expression = None

    class _Params:
        def __init__(self, param):
            self._param = param

        def itemByName(self, _name):
            return self._param

    def _target(self):
        param = self._Param()
        return type("Target", (), {"parameters": self._Params(param)})(), param

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_a_non_finite_value_is_refused(self, handler_module, value):
        # Refused before the call's broad except, so it classifies as
        # INVALID_INPUT rather than False - which callers read as "no such
        # parameter" and would answer by retrying the same value.
        target, param = self._target()
        with pytest.raises(ValueError, match="invalid parameter value"):
            handler_module.CommandHandler._set_cam_parameter(target, "stepdown", value)
        assert param.expression is None

    def test_a_finite_value_is_written(self, handler_module):
        target, param = self._target()
        assert handler_module.CommandHandler._set_cam_parameter(target, "stepdown", 2.0)
        assert param.expression == "2.0"


class TestValueInputFor:
    """The real-or-expression decision, which the handler adapters just apply."""

    def test_a_finite_float_is_written_as_a_real(self):
        assert parameter_units.value_input_for(2.5) == ("real", 2.5)

    def test_an_int_is_written_as_a_real(self):
        assert parameter_units.value_input_for(7) == ("real", 7.0)

    def test_an_int_too_large_for_float_becomes_an_expression(self):
        huge = json.loads("1" + "0" * 400)
        kind, payload = parameter_units.value_input_for(huge)
        assert kind == "expression"
        assert payload == str(huge)

    @pytest.mark.parametrize("expression", ["boxL", "56 mm", "outer - 2*wall_t"])
    def test_a_string_expression_passes_through(self, expression):
        assert parameter_units.value_input_for(expression) == ("expression", expression)

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_a_non_finite_number_is_refused(self, value):
        with pytest.raises(ValueError, match="invalid parameter value"):
            parameter_units.value_input_for(value)


class TestCreateBoxParametricRefusesNonFinite:
    """The call site, not just the decision: fails if the guards stop being called."""

    @pytest.mark.parametrize(
        "override",
        [
            {"length": float("inf")},
            {"width": float("nan")},
            {"height": float("-inf")},
            {"origin_x": float("inf")},
            {"origin_y": float("nan")},
            {"origin_z": float("-inf")},
        ],
    )
    def test_the_guard_fires_before_any_fusion_call(self, bound_handler, override):
        # ``bound_handler(None)``: the guards run before the design is ever
        # reached, which is exactly the ordering being pinned. If they moved
        # below ``self._root()`` this would raise AttributeError instead.
        handler = bound_handler(None)
        args = {"length": 1, "width": 1, "height": 1, **override}
        with pytest.raises(ValueError, match="invalid parameter value"):
            handler.create_box_parametric(**args)

    def test_the_mock_refuses_the_same_value(self):
        # Mirrors the entry guard: mock mode must not report a box the add-in
        # would refuse, or a caller develops against a fiction.
        result = mock_command(
            "create_box_parametric",
            {"length": float("inf"), "width": 1, "height": 1},
        )
        assert result.get("ok") is False
        assert result.get("error_kind") == "INVALID_INPUT"


class TestCamEntryGuards:
    """The CAM guards, pinned at the call site rather than inside the helper.

    ``bound_handler(None)`` cannot satisfy ``_get_cam``; reaching it would be an
    AttributeError, so a passing test proves the guard fired first — and a guard
    moved back below ``setups.add`` / ``operations.add`` fails here.
    """

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"stock_offset_sides": float("inf")},
            {"stock_offset_top": float("nan")},
            {"stock_offset_bottom": float("-inf")},
        ],
    )
    def test_setup_refuses_a_non_finite_stock_offset_first(self, bound_handler, kwargs):
        # All three offsets, not just the first: a guard deleted from any one of
        # them must fail here, which is the failure mode this test exists for.
        handler = bound_handler(None)
        with pytest.raises(ValueError, match="invalid parameter value"):
            handler.cam_create_setup("Body1", **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"stepdown": float("inf")},
            {"stepover": float("nan")},
            {"feed_rate": float("-inf")},
            {"spindle_speed": float("inf")},
            {"tool_number": float("inf")},
        ],
    )
    def test_operation_refuses_a_non_finite_value_first(self, bound_handler, kwargs):
        handler = bound_handler(None)
        with pytest.raises(ValueError, match="invalid parameter value"):
            handler.cam_create_operation("Setup1", "adaptive", **kwargs)
