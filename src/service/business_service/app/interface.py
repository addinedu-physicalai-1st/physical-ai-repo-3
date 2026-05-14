from typing import Protocol


class StatusNotifier(Protocol):
    def notify_status(self, seq: int) -> bool:
        """Send a STATUS notification for the received health-check sequence."""
        ...
