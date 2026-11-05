"""A bridge that records what it was asked to do instead of doing it.

``_handle_client`` only uses ``submit(command) -> dict``, so a target can hand
it this and then assert on what reached the bridge.
"""


class RecordingBridge:
    def __init__(self) -> None:
        self.commands: list[dict] = []

    def submit(self, command: dict) -> dict:
        self.commands.append(command)
        return {"status": "success", "result": {"ok": True}}
