import json
import logging
import signal
import threading

from prometheus_client import Counter, start_http_server

from packages.campus_common.config import load_settings
from packages.campus_common.database import Database
from packages.campus_common.http import configure_logging
from services.hr.app.domain.notifications import send_pending

log = logging.getLogger("campus.hr.worker")


def main() -> None:
    settings = load_settings("hr")
    configure_logging("hr-worker", settings.log_host)
    database = Database(settings.database_url)
    stop = threading.Event()
    for code in (signal.SIGTERM, signal.SIGINT):
        signal.signal(code, lambda *_: stop.set())
    delivered = Counter("campus_notification_emails_sent_total", "Notification emails delivered", ["service"])
    start_http_server(9100)
    log.info(json.dumps({"service": "hr-worker", "event": "started"}))
    while not stop.is_set():
        try:
            sent = send_pending(database, settings.smtp_host, settings.smtp_port, settings.mail_from)
            if sent:
                delivered.labels("hr").inc(sent)
                log.info(json.dumps({"service": "hr-worker", "event": "emails_sent", "count": sent}))
        except Exception as error:  # noqa: BLE001 - keep the notifier alive across database restarts
            log.error(json.dumps({"service": "hr-worker", "event": "notify_failed", "reason": repr(error)}))
        stop.wait(10)


if __name__ == "__main__":
    main()
