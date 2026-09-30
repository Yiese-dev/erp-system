import json
import logging
import signal
import threading
from functools import partial

from prometheus_client import Gauge, start_http_server

from packages.campus_common.config import load_settings
from packages.campus_common.database import Database, utcnow
from packages.campus_common.events import consume_forever, pending_count, relay_forever
from packages.campus_common.http import configure_logging
from services.academic.app.models import OutboxEvent, ProcessedEvent, Registration

INVOICE_CREATED = "finance.invoice.created.v1"
INVOICE_SETTLED = "finance.invoice.settled.v1"
BILLING_ISSUE = "finance.billing.issue.v1"
STATUS = {INVOICE_CREATED: "invoiced", INVOICE_SETTLED: "paid", BILLING_ISSUE: "issue"}
log = logging.getLogger("campus.academic.worker")


def handle_finance_event(database: Database, event: dict) -> None:
    """Keeps Academic's billing-status projection eventually consistent with Finance."""
    with database.session(event["tenant_id"]) as session:
        if session.get(ProcessedEvent, event["event_id"]):
            return
        registration = session.get(Registration, event["data"].get("registration_id", ""))
        if registration is not None and event["event_type"] in STATUS and registration.billing_status != "paid":
            registration.billing_status = STATUS[event["event_type"]]
            registration.invoice_number = event["data"].get("invoice_number") or registration.invoice_number
        session.add(ProcessedEvent(event_id=event["event_id"], event_type=event["event_type"], tenant_id=event["tenant_id"],
                                   processed_at=utcnow()))


def main() -> None:
    settings = load_settings("academic")
    configure_logging("academic-worker", settings.log_host)
    database = Database(settings.database_url)
    stop = threading.Event()
    for code in (signal.SIGTERM, signal.SIGINT):
        signal.signal(code, lambda *_: stop.set())
    backlog = Gauge("campus_outbox_pending", "Committed events not yet published", ["service"])
    start_http_server(9100)
    workers = [
        threading.Thread(target=relay_forever, args=(database, OutboxEvent, settings.broker_url, stop), daemon=True),
        threading.Thread(target=consume_forever, daemon=True, args=(
            settings.broker_url, "academic.billing-status", tuple(STATUS), partial(handle_finance_event, database), stop)),
    ]
    for worker in workers:
        worker.start()
    log.info(json.dumps({"service": "academic-worker", "event": "started"}))
    while not stop.wait(15):
        try:
            backlog.labels("academic").set(pending_count(database, OutboxEvent))
        except Exception as error:  # noqa: BLE001 - metrics must not stop the worker
            log.warning(json.dumps({"service": "academic-worker", "event": "metrics_failed", "reason": repr(error)}))


if __name__ == "__main__":
    main()
