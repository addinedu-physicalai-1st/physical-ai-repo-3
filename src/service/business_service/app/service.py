from app.interface import StatusNotifier


class BusinessService:
    def __init__(self, status_notifier: StatusNotifier):
        self.status_notifier = status_notifier

    def run_health_test(self, seq: int) -> None:
        self.status_notifier.notify_status(seq)
