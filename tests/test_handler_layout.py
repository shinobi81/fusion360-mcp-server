"""The split's two invariants: every command has one home, and the shell is empty.

``command_handler.py`` used to declare all 97 commands in one class. It is now a
shell - ``HandlerBase`` plus one class per domain - so the layout is what keeps the
modules honest, and both halves of that layout are asserted here:

* every name in ``HandlerBase._COMMAND_NAMES`` is declared by **exactly one** class
  in the handler's MRO. Two declarations is a copy nobody deleted, which the mixin
  order would silently resolve; none is a command the dispatch table names and no
  module answers, which ``__init__`` would only fail on once Fusion loads it.
* ``CommandHandler``'s body declares nothing. Anything left there is a command in the
  old file, where the domain that owns it cannot find it.

The first test resolves through ``cls.__mro__`` and ``vars`` the way
``scripts/reload_addin.py`` reads the running class, because the question is what the
composed handler answers - not what a file contains. The second reads the source with
``ast``, because "declares nothing" is a property of the file.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMMAND_HANDLER = (
    Path(__file__).resolve().parent.parent / "addon" / "server" / "command_handler.py"
)


def command_owners(handler_class) -> dict[str, list[str]]:
    """``{command name: [declaring class, ...]}`` for the handler's whole MRO.

    ``vars`` per class rather than ``dir``: ``dir`` lists what the class answers, so
    a name declared twice would appear once and the duplicate would be invisible -
    which is the thing this reports. A class is named by its qualname and module, so
    a failure says which two homes a command has.
    """
    return {
        name: [
            f"{klass.__module__}.{klass.__qualname__}"
            for klass in handler_class.__mro__
            if name in vars(klass)
        ]
        for name in handler_class._COMMAND_NAMES
    }


def test_every_command_resolves_to_exactly_one_module(handler_module):
    """Each of the 97 commands is declared once, and by a class the handler mixes in."""
    handler_class = handler_module.CommandHandler
    owners = command_owners(handler_class)

    assert len(owners) == len(handler_class._COMMAND_NAMES)
    homed = {name: found for name, found in owners.items() if len(found) == 1}
    assert homed == owners, (
        "commands declared by other than exactly one class: "
        + ", ".join(
            f"{name} -> {found or 'nothing'}"
            for name, found in owners.items()
            if len(found) != 1
        )
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
