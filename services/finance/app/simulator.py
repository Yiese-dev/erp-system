import hmac
import json
import logging
import os
import threading
import time
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from packages.campus_common.config import LOCAL_SECRET
from packages.campus_common.http import configure_logging
from services.finance.app.domain.payments import sign

log = logging.getLogger("campus.momo-simulator")
DELAY_SECONDS = 4


class RequestToPay(BaseModel):
    reference: str = Field(min_length=8, max_length=64)
    amount: int = Field(gt=0)
    currency: str = Field(pattern="^XAF$")
    msisdn: str = Field(pattern=r"^6\d{8}$")
    provider: str = Field(pattern="^(mtn_momo|orange_money)$")
    payer_message: str = Field("", max_length=100)
    callback_url: str = Field(max_length=300)


def outcome(msisdn: str) -> tuple[str | None, str]:
    """Deterministic sandbox rules: numbers ending in 0 are declined, ending in 9 never answer (timeout)."""
    if msisdn.endswith("9"):
        return None, "timeout"
    if msisdn.endswith("0"):
        return "FAILED", "Insufficient balance on the payer wallet"
    return "SUCCESSFUL", "Approved by payer"


def create_simulator():
    webhook_secret = os.getenv("WEBHOOK_SECRET", LOCAL_SECRET)
    api_key = os.getenv("SIMULATOR_KEY", LOCAL_SECRET)
    callback_base = os.getenv("CALLBACK_BASE_URL", "http://gateway:8080").rstrip("/")
    configure_logging("momo-simulator", os.getenv("LOG_HOST", ""))
    app = FastAPI(title="Campus ERP | Mobile Money Simulator (MTN MoMo / Orange Money)", version="1.0.0")
    allowed_prefix = callback_base + "/api/v1/finance/payment-webhooks/simulated/"

    def deliver(payload: RequestToPay) -> None:
        time.sleep(DELAY_SECONDS)
        status, reason = outcome(payload.msisdn)
        if status is None:
            log.info(json.dumps({"service": "momo-simulator", "event": "timeout", "reference": payload.reference}))
            return
        body = json.dumps({"event_id": f"sim-{uuid4().hex}", "reference": payload.reference, "status": status, "amount": payload.amount,
                           "currency": payload.currency, "provider": payload.provider, "reason": reason}).encode()
        for attempt in range(3):
            timestamp = str(int(time.time()))
            try:
                response = httpx.post(payload.callback_url, content=body, timeout=10, headers={
                    "Content-Type": "application/json", "X-Timestamp": timestamp, "X-Signature": sign(webhook_secret, timestamp, body)})
                log.info(json.dumps({"service": "momo-simulator", "event": "callback", "status": response.status_code, "reference": payload.reference}))
                if response.status_code < 500:
                    return
            except httpx.HTTPError as error:
                log.warning(json.dumps({"service": "momo-simulator", "event": "callback_failed", "reason": repr(error)}))
            time.sleep(2 ** attempt)

    @app.post("/v1/requesttopay", status_code=202)
    def request_to_pay(payload: RequestToPay, background: BackgroundTasks, x_api_key: str = Header("")):
        if not hmac.compare_digest(x_api_key, api_key):
            raise HTTPException(401, "Invalid API key")
        if not payload.callback_url.startswith(allowed_prefix):
            raise HTTPException(422, "Callback URL is not registered for this merchant")
        background.add_task(threading.Thread(target=deliver, args=(payload,), daemon=True).start)
        return {"status": "PENDING", "reference": payload.reference}

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": "momo-simulator"}

    return app
