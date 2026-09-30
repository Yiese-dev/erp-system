import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

import pika
from pika.exceptions import AMQPError
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from packages.campus_common.database import UTCDateTime, utcnow

EXCHANGE = "campus.events"
RETRY_EXCHANGE = "campus.retry"
DEAD_EXCHANGE = "campus.dead"
MAX_ATTEMPTS = 5
RETRY_DELAY_MS = 5000
log = logging.getLogger("campus.events")


class PermanentEventError(Exception):
    """The message can never succeed (malformed or unsupported) and must go straight to the dead-letter queue."""


def event_tables(base):
    class OutboxEvent(base):
        __tablename__ = "outbox_events"
        id: Mapped[str] = mapped_column(String(64), primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String(64), index=True)
        event_type: Mapped[str] = mapped_column(String(120))
        payload: Mapped[dict] = mapped_column(JSON)
        correlation_id: Mapped[str] = mapped_column(String(64))
        occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
        published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    class ProcessedEvent(base):
        __tablename__ = "processed_events"
        event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        event_type: Mapped[str] = mapped_column(String(120))
        tenant_id: Mapped[str] = mapped_column(String(64))
        processed_at: Mapped[datetime] = mapped_column(UTCDateTime)

    return OutboxEvent, ProcessedEvent


def record_event(session, outbox_model, tenant_id: str, event_type: str, payload: dict, correlation_id: str | None = None):
    event = outbox_model(id=str(uuid4()), tenant_id=tenant_id, event_type=event_type, payload=payload,
                         correlation_id=correlation_id or str(uuid4()), occurred_at=utcnow(), published_at=None)
    session.add(event)
    return event


def envelope(row) -> dict[str, Any]:
    return {"event_id": row.id, "event_type": row.event_type, "schema_version": 1, "tenant_id": row.tenant_id,
            "occurred_at": row.occurred_at.isoformat(), "correlation_id": row.correlation_id, "data": row.payload}


def validate_envelope(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise PermanentEventError("Event must be an object.")
    for key in ("event_id", "event_type", "tenant_id", "correlation_id"):
        if not isinstance(event.get(key), str) or not event[key] or len(event[key]) > 120:
            raise PermanentEventError(f"Event field {key} is invalid.")
    if event.get("schema_version") != 1 or not isinstance(event.get("data"), dict):
        raise PermanentEventError("Unsupported event schema.")
    return event


def declare(channel, queue: str | None = None, bindings: tuple[str, ...] = ()) -> None:
    channel.exchange_declare(EXCHANGE, "topic", durable=True)
    channel.exchange_declare(RETRY_EXCHANGE, "direct", durable=True)
    channel.exchange_declare(DEAD_EXCHANGE, "direct", durable=True)
    if not queue:
        return
    channel.queue_declare(queue, durable=True, arguments={"x-dead-letter-exchange": RETRY_EXCHANGE,
                                                          "x-dead-letter-routing-key": queue})
    channel.queue_declare(f"{queue}.retry", durable=True, arguments={
        "x-message-ttl": RETRY_DELAY_MS, "x-dead-letter-exchange": "", "x-dead-letter-routing-key": queue})
    channel.queue_declare(f"{queue}.dead", durable=True)
    channel.queue_bind(f"{queue}.retry", RETRY_EXCHANGE, routing_key=queue)
    channel.queue_bind(f"{queue}.dead", DEAD_EXCHANGE, routing_key=queue)
    for key in bindings:
        channel.queue_bind(queue, EXCHANGE, routing_key=key)


def relay_once(database, outbox_model, channel, batch: int = 50) -> int:
    """Publish committed outbox rows; a crash after publish but before commit re-publishes (at-least-once)."""
    with database.session() as session:
        rows = session.scalars(select(outbox_model).where(outbox_model.published_at.is_(None))
                               .order_by(outbox_model.occurred_at).limit(batch).with_for_update(skip_locked=True)).all()
        for row in rows:
            channel.basic_publish(
                EXCHANGE, row.event_type, json.dumps(envelope(row)).encode(),
                pika.BasicProperties(content_type="application/json", delivery_mode=2, message_id=row.id,
                                     type=row.event_type, correlation_id=row.correlation_id),
                mandatory=True)
            row.published_at = utcnow()
        return len(rows)


def pending_count(database, outbox_model) -> int:
    with database.session() as session:
        return len(session.scalars(select(outbox_model.id).where(outbox_model.published_at.is_(None)).limit(10000)).all())


def rejection_count(properties, queue: str) -> int:
    deaths = (properties.headers or {}).get("x-death") or []
    return sum(int(item.get("count", 0)) for item in deaths if item.get("queue") == queue and item.get("reason") == "rejected")


def deliver(channel, queue: str, method, properties, body: bytes, handler: Callable[[dict], None]) -> str:
    try:
        handler(validate_envelope(json.loads(body)))
    except (PermanentEventError, json.JSONDecodeError, UnicodeDecodeError) as error:
        log.error(json.dumps({"event": "dead_letter", "queue": queue, "reason": str(error)}))
        channel.basic_publish(DEAD_EXCHANGE, queue, body, properties)
        channel.basic_ack(method.delivery_tag)
        return "dead"
    except Exception as error:  # noqa: BLE001 - transient failures are retried by the broker
        attempts = rejection_count(properties, queue) + 1
        if attempts >= MAX_ATTEMPTS:
            log.error(json.dumps({"event": "dead_letter", "queue": queue, "attempts": attempts, "reason": repr(error)}))
            channel.basic_publish(DEAD_EXCHANGE, queue, body, properties)
            channel.basic_ack(method.delivery_tag)
            return "dead"
        log.warning(json.dumps({"event": "retry", "queue": queue, "attempts": attempts, "reason": repr(error)}))
        channel.basic_nack(method.delivery_tag, requeue=False)
        return "retry"
    channel.basic_ack(method.delivery_tag)
    return "ack"


def _connect(broker_url: str):
    parameters = pika.URLParameters(broker_url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 30
    return pika.BlockingConnection(parameters)


def relay_forever(database, outbox_model, broker_url: str, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            connection = _connect(broker_url)
            channel = connection.channel()
            channel.confirm_delivery()
            declare(channel)
            while not stop.is_set():
                if not relay_once(database, outbox_model, channel):
                    connection.sleep(1.0)
            connection.close()
        except (AMQPError, OSError) as error:
            log.warning(json.dumps({"event": "relay_reconnect", "reason": repr(error)}))
            stop.wait(3)
        except Exception as error:  # noqa: BLE001 - keep the relay alive across database restarts
            log.error(json.dumps({"event": "relay_error", "reason": repr(error)}))
            stop.wait(3)


def consume_forever(broker_url: str, queue: str, bindings: tuple[str, ...], handler, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            connection = _connect(broker_url)
            channel = connection.channel()
            declare(channel, queue, bindings)
            channel.basic_qos(prefetch_count=10)
            for method, properties, body in channel.consume(queue, inactivity_timeout=1.0):
                if stop.is_set():
                    break
                if method is not None:
                    deliver(channel, queue, method, properties, body, handler)
            channel.cancel()
            connection.close()
        except (AMQPError, OSError) as error:
            log.warning(json.dumps({"event": "consumer_reconnect", "queue": queue, "reason": repr(error)}))
            stop.wait(3)
