"""The split's three invariants: one home per command, one per helper, an empty shell.

``command_handler.py`` used to declare all 97 commands in one class. It is now a
shell - ``HandlerBase`` plus one class per domain - so the layout is what keeps the
modules honest, and all three halves of that layout are asserted here:

* every name in ``HandlerBase._COMMAND_NAMES`` is declared by **exactly one** class
  in the handler's MRO. Two declarations is a copy nobody deleted, which the mixin
  order would silently resolve; none is a command the dispatch table names and no
  module answers, which ``__init__`` would only fail on once Fusion loads it.
* no *other* method name is declared by two classes either. A helper copied into a
  second domain rather than moved to ``handler_base`` breaks the same rule in the
  place ``_COMMAND_NAMES`` cannot see it, and the reload check compares sets of
  names, so it agrees with itself either way.
* ``CommandHandler``'s body declares nothing. Anything left there is a command in the
  old file, where the domain that owns it cannot find it.

The first two resolve through ``cls.__mro__`` and ``vars`` the way
``scripts/reload_addin.py`` reads the running class, because the question is what the
composed handler answers - not what a file contains. The third reads the source with
``ast``, because "declares nothing" is a property of the file.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMMAND_HANDLER = (
    Path(__file__).resolve().parent.parent / "addon" / "server" / "command_handler.py"
)


def method_owners(handler_class) -> dict[str, list[str]]:
    """``{method name: [declaring class, ...]}`` for every method the MRO declares.

    ``vars`` per class rather than ``dir``: ``dir`` lists what the class answers, so
    a name declared twice would appear once and the duplicate would be invisible -
    which is the thing this reports. A class is named by its qualname and module, so
    a failure says which two homes a name has. Dunders and the classes' attribute
    tables are left out: ``__init__`` is ``HandlerBase``'s by design, and
    ``_COMMAND_NAMES`` is data, not a method.
    """
    return {
        name: [
            f"{klass.__module__}.{klass.__qualname__}"
            for klass in handler_class.__mro__
            if name in vars(klass)
        ]
        for klass in handler_class.__mro__
        for name in vars(klass)
        if callable(getattr(handler_class, name)) and not name.startswith("__")
    }


def test_every_command_resolves_to_exactly_one_module(handler_module):
    """Each of the 99 commands is declared once, and by a class the handler mixes in."""
    handler_class = handler_module.CommandHandler
    declared = method_owners(handler_class)
    # ``get``, not a filter: the MRO is what ``declared`` is keyed by, so a command
    # nothing declares is absent from it, and only ``_COMMAND_NAMES`` knows it was
    # supposed to exist. Empty here means every name below went unchecked.
    owners = {name: declared.get(name, []) for name in handler_class._COMMAND_NAMES}

    assert owners, "``_COMMAND_NAMES`` names no command: nothing is checked below"
    homed = {name: found for name, found in owners.items() if len(found) == 1}
    assert homed == owners, (
        "commands declared by other than exactly one class: "
        + ", ".join(
            f"{name} -> {found or 'nothing'}"
            for name, found in owners.items()
            if len(found) != 1
        )
    )


def test_no_helper_is_declared_by_two_classes(handler_module):
    """A helper in two domains is the same drift, in the place commands cannot see it.

    ``handler_base`` exists so a helper two domains call has one home; a copy left
    behind in a domain is dead code the mixin order hides, and because the reload check
    compares *sets* of method names, it reports ok for exactly that shape.
    """
    duplicated = {
        name: found
        for name, found in method_owners(handler_module.CommandHandler).items()
        if len(found) > 1
    }

    assert duplicated == {}, "methods declared by more than one class: " + ", ".join(
        f"{name} -> {found}" for name, found in duplicated.items()
    )


def test_command_handler_declares_nothing_but_its_docstring():
    """``CommandHandler`` is a composition: its body is its docstring, nothing else.

    Not just "no commands": an attribute table left behind would be read by a domain
    that no longer sits beside it, and the shell would keep a second place to look.
    """
    tree = ast.parse(COMMAND_HANDLER.read_text(encoding="utf-8"))
    (command_handler,) = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CommandHandler"
    ]

    declared = [
        node for node in command_handler.body if isinstance(node, ast.FunctionDef)
    ]
    assert declared == [], (
        "CommandHandler still declares "
        + ", ".join(node.name for node in declared)
        + "; move each to the module whose commands call it"
    )

    docstring, *rest = command_handler.body
    assert isinstance(docstring, ast.Expr) and isinstance(
        docstring.value, ast.Constant
    ), "CommandHandler's body must start with its docstring"
    assert rest == [], (
        "CommandHandler's body is its docstring and nothing else: "
        + ", ".join(ast.dump(node)[:40] for node in rest)
    )
