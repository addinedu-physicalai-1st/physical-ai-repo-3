import logging

from app.tcp import StatusNotifier


class MocaService:
    def __init__(
        self,
        status_notifiers: list[StatusNotifier],
        logger: logging.Logger,
    ):
        self.status_notifiers = status_notifiers
        self.logger = logger

    def run_health_test(self, seq: int) -> None:
        self.logger.info("running moca_service fan-out health test seq=%s", seq)
        for status_notifier in self.status_notifiers:
            status_notifier.notify_status(seq)

    def handle_status(self, seq: int, peer: tuple[str, int]) -> None:
        self.logger.info("received STATUS seq=%s from %s:%s", seq, peer[0], peer[1])
