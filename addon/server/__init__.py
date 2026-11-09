"""Fusion360MCP Server Package — v2 (CustomEvent bridge architecture)"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_PATH = os.path.join(os.path.expanduser("~"), "fusion360mcp.log")

#: Set once by :func:`configure`.  A module flag rather than an inspection of the
#: logger, so a second call cannot attach a second file handler and double every line.
_configured = False


def configure() -> None:
    """Attach the log handlers, once.  The add-in's entry point calls this first thing.

    Not at import time: ``RotatingFileHandler`` opens (and so creates) its file when it
    is constructed, and three modules call :func:`get_logger` at module scope.  Wiring
    the handlers here would mean that merely importing the add-in - which the test suite
    does - writes to the user's home directory.

    ``LOG_PATH`` is read on each call rather than captured, so it stays patchable.
    """
    global _configured
    if _configured:
        return

    logger = logging.getLogger("fusion360mcp")
    logger.setLevel(logging.DEBUG)

    # File handler — rotates at 2 MB, keeps 3 backups
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    # Also echo to Fusion's TEXT COMMANDS (stdout/stderr)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("[MCP] %(message)s"))
    logger.addHandler(stream_handler)

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger.  ``get_logger("bridge")`` → ``fusion360mcp.bridge``.

    Pure: the handlers come from :func:`configure`, so this is safe to call at import.
    """
    logger = logging.getLogger("fusion360mcp")
    return logger.getChild(name) if name else logger
