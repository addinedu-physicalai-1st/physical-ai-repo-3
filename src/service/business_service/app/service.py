import logging

from app.tcp import StatusNotifier


class BusinessService:
    def __init__(self, status_notifiers: list[StatusNotifier], logger: logging.Logger):
        self.status_notifiers = status_notifiers
        self.logger = logger

    def run_health_test(self, seq: int) -> None:
        self.logger.info("running business_service fan-out health test seq=%s", seq)
        for status_notifier in self.status_notifiers:
            status_notifier.notify_status(seq)
