import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from packages.campus_common.database import LOCAL_TZ, new_id, utcnow
from packages.campus_common.errors import DomainError
from packages.campus_common.events import record_event
from services.finance.app.domain.billing import next_number, status_event
from services.finance.app.domain.ledger import SETTLEMENT_ACCOUNTS, post_entry
from services.finance.app.models import Invoice, KnownTenant, OutboxEvent, Payment, PaymentIntent, ProviderEvent, Receipt

PROVIDERS = {"mtn_momo": "MTN Mobile Money", "orange_money": "Orange Money"}
MANUAL_METHODS = {"bank_transfer": "Bank transfer", "cash": "Cash"}
PAYMENT_RECEIVED = "finance.payment.received.v1"
SIGNATURE_TOLERANCE_SECONDS = 300
INTENT_TIMEOUT = timedelta(minutes=3)
MINIMUM_PAYMENT = 100


def normalize_msisdn(raw: str) -> str:
    digits = re.sub(r"[\s\-()]", "", raw)
    digits = re.sub(r"^(\+?237)", "", digits)
    if not re.fullmatch(r"6\d{8}", digits):
        raise DomainError("Enter a Cameroonian mobile number such as 6XX XXX XXX.", 422)
    return digits


def mask(msisdn: str) -> str:
    return f"{msisdn[:3]}****{msisdn[-2:]}"


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class SimulatedMobileMoneyProvider:
    """Mirrors the MTN MoMo / Orange Money request-to-pay + callback flow; replaceable by a real adapter."""

    def __init__(self, base_url: str, api_key: str, callback_base_url: str):
        self.base_url, self.api_key, self.callback_base_url = base_url.rstrip("/"), api_key, callback_base_url.rstrip("/")

    def request_to_pay(self, tenant_id: str, intent: PaymentIntent, msisdn: str) -> None:
        response = httpx.post(f"{self.base_url}/v1/requesttopay", timeout=5, headers={"X-Api-Key": self.api_key}, json={
            "reference": intent.reference, "amount": intent.amount, "currency": intent.currency, "msisdn": msisdn,
            "provider": intent.provider, "payer_message": "Tuition payment",
            "callback_url": f"{self.callback_base_url}/api/v1/finance/payment-webhooks/simulated/{tenant_id}"})
        response.raise_for_status()


def outstanding(session, invoice: Invoice) -> int:
    pending = session.scalar(select(func.coalesce(func.sum(PaymentIntent.amount), 0))
                             .where(PaymentIntent.invoice_id == invoice.id, PaymentIntent.status == "pending")) or 0
    return invoice.total - invoice.paid - int(pending)


def start_payment(session, tenant_id: str, invoice_id: str, actor_user_id: str, staff: bool, provider: str, msisdn: str,
                  amount: int, idempotency_key: str) -> tuple[PaymentIntent, bool]:
    if provider not in PROVIDERS:
        raise DomainError("Choose MTN Mobile Money or Orange Money.", 422)
    existing = session.scalar(select(PaymentIntent).where(PaymentIntent.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.invoice_id != invoice_id or existing.amount != amount:
            raise DomainError("This idempotency key was already used for a different payment.", 409)
        return existing, False
    invoice = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None or (not staff and invoice.student_user_id != actor_user_id):
        raise DomainError("Invoice not found.", 404)
    if invoice.status not in ("issued", "partially_paid"):
        raise DomainError(f"Invoice {invoice.number} is {invoice.status.replace('_', ' ')}.", 409)
    available = outstanding(session, invoice)
    if amount < MINIMUM_PAYMENT or amount > available:
        raise DomainError(f"Amount must be between {MINIMUM_PAYMENT} and {available} FCFA (balance less payments in progress).", 409,
                          details={"available": available})
    intent = PaymentIntent(id=new_id("pmi"), tenant_id=tenant_id, invoice_id=invoice.id, provider=provider,
                           msisdn_masked=mask(normalize_msisdn(msisdn)), amount=amount, currency="XAF", status="pending",
                           idempotency_key=idempotency_key, reference=uuid4().hex, initiated_by=actor_user_id, created_at=utcnow())
    session.add(intent)
    session.flush()
    return intent, True


def apply_payment(session, tenant_id: str, invoice: Invoice, amount: int, method: str, reference: str, recorded_by: str,
                  intent: PaymentIntent | None = None, paid_at: datetime | None = None) -> tuple[Payment, Receipt]:
    """One ACID unit: payment row, balanced journal, invoice balance, receipt and outbox events commit or roll back together."""
    if amount <= 0 or amount > invoice.total - invoice.paid:
        raise DomainError(f"Payment of {amount} FCFA exceeds the outstanding balance of {invoice.total - invoice.paid} FCFA.", 409)
    when = paid_at or utcnow()
    payment = Payment(id=new_id("pay"), tenant_id=tenant_id, invoice_id=invoice.id, intent_id=intent.id if intent else None, amount=amount,
                      method=method, reference=reference, recorded_by=recorded_by, paid_at=when)
    session.add(payment)
    session.flush()
    local_day = when.astimezone(LOCAL_TZ).date()
    post_entry(session, tenant_id, local_day, f"{PROVIDERS.get(method) or MANUAL_METHODS.get(method, method)} payment {invoice.number}",
               "payment", payment.id, [(SETTLEMENT_ACCOUNTS[method], amount, 0), ("1200", 0, amount)])
    invoice.paid += amount
    invoice.status = "paid" if invoice.paid == invoice.total else "partially_paid"
    receipt = Receipt(id=new_id("rct"), tenant_id=tenant_id, number=next_number(session, tenant_id, "receipt", "RCT", local_day.year),
                      payment_id=payment.id, invoice_id=invoice.id, issued_at=when)
    session.add(receipt)
    record_event(session, OutboxEvent, tenant_id, PAYMENT_RECEIVED, {"registration_id": invoice.registration_id, "invoice_id": invoice.id,
                                                                     "invoice_number": invoice.number, "amount": amount, "method": method,
                                                                     "receipt_number": receipt.number})
    if invoice.status == "paid":
        status_event(session, tenant_id, invoice)
    session.flush()
    return payment, receipt


def verify_signature(secret: str, timestamp: str | None, signature: str | None, body: bytes, now: int) -> None:
    if not timestamp or not signature or not timestamp.isdigit() or abs(now - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
        raise DomainError("Invalid or expired webhook signature.", 401)
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise DomainError("Invalid or expired webhook signature.", 401)


def parse_callback(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DomainError("Malformed callback.", 400) from error
    valid = (isinstance(payload, dict) and isinstance(payload.get("event_id"), str) and 0 < len(payload["event_id"]) <= 80
             and isinstance(payload.get("reference"), str) and payload.get("status") in ("SUCCESSFUL", "FAILED")
             and isinstance(payload.get("amount"), int) and payload.get("currency") == "XAF")
    if not valid:
        raise DomainError("Malformed callback.", 400)
    return payload


def handle_callback(database, secret: str, tenant_id: str, timestamp: str | None, signature: str | None, body: bytes, now: int) -> dict:
    verify_signature(secret, timestamp, signature, body, now)
    payload = parse_callback(body)
    with database.session(tenant_id) as session:
        if session.get(ProviderEvent, payload["event_id"]):
            return {"status": "duplicate"}
        intent = session.scalar(select(PaymentIntent).where(PaymentIntent.reference == payload["reference"]).with_for_update())
        if intent is None:
            raise DomainError("Unknown payment reference.", 404)
        session.add(ProviderEvent(id=payload["event_id"], tenant_id=tenant_id, intent_id=intent.id, status=payload["status"],
                                  received_at=utcnow(), payload=payload))
        if intent.status != "pending":
            return {"status": "ignored", "intent_status": intent.status}
        intent.completed_at = utcnow()
        if payload["amount"] != intent.amount:
            intent.status, intent.failure_reason = "failed", "Provider amount does not match the payment request."
            return {"status": "rejected"}
        if payload["status"] == "FAILED":
            intent.status, intent.failure_reason = "failed", str(payload.get("reason") or "Declined by provider")[:200]
            return {"status": "failed"}
        invoice = session.scalar(select(Invoice).where(Invoice.id == intent.invoice_id).with_for_update())
        if intent.amount > invoice.total - invoice.paid:
            intent.status, intent.failure_reason = "failed", "Invoice balance changed; the provider must refund this collection."
            return {"status": "rejected"}
        payment, receipt = apply_payment(session, tenant_id, invoice, intent.amount, intent.provider, intent.reference, intent.initiated_by,
                                         intent=intent)
        intent.status = "succeeded"
        return {"status": "settled", "receipt_number": receipt.number, "payment_id": payment.id}


def expire_stale_intents(database, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - INTENT_TIMEOUT
    expired = 0
    with database.session() as session:
        tenants = session.scalars(select(KnownTenant.id)).all()
    for tenant_id in tenants:
        with database.session(tenant_id) as session:
            for intent in session.scalars(select(PaymentIntent).where(PaymentIntent.status == "pending", PaymentIntent.created_at < cutoff)
                                          .with_for_update(skip_locked=True)).all():
                intent.status, intent.failure_reason, intent.completed_at = "expired", "No confirmation from the provider in time.", utcnow()
                expired += 1
    return expired
