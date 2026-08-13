"""Razorpay one-time pass checkout and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.config import (
    GST_RATE,
    PLANS,
    PRICES_INCLUDE_GST,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
)
from jobsearch_saas.entitlements import activate_plan


def razorpay_configured() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def plan_price_breakdown(plan_id: str) -> dict[str, int]:
    plan = PLANS[plan_id]
    amount = int(plan["amount_inr"])
    if amount <= 0:
        return {"base_paise": 0, "gst_paise": 0, "total_paise": 0}
    if PRICES_INCLUDE_GST:
        total = amount
        base = int(round(total / (1 + GST_RATE)))
        gst = total - base
    else:
        base = amount
        gst = int(round(base * GST_RATE))
        total = base + gst
    return {"base_paise": base, "gst_paise": gst, "total_paise": total}


def create_order(user_id: str, plan_id: str) -> dict[str, Any]:
    if plan_id not in PLANS or plan_id == "free":
        raise ValueError("Choose a paid pass")
    breakdown = plan_price_breakdown(plan_id)
    payment_id = str(uuid.uuid4())
    order_id = f"order_dev_{payment_id[:8]}"
    if razorpay_configured():
        import urllib.request

        auth = (RAZORPAY_KEY_ID + ":" + RAZORPAY_KEY_SECRET).encode()
        import base64

        basic = base64.b64encode(auth).decode()
        payload = json.dumps(
            {
                "amount": breakdown["total_paise"],
                "currency": "INR",
                "receipt": payment_id[:30],
                "notes": {"user_id": user_id, "plan_id": plan_id},
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.razorpay.com/v1/orders",
            data=payload,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            order = json.loads(resp.read().decode())
        order_id = order["id"]

    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO payments (
                id, user_id, plan_id, razorpay_order_id, amount_paise, gst_paise,
                currency, status, invoice_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'INR', 'created', ?, ?)
            """,
            (
                payment_id,
                user_id,
                plan_id,
                order_id,
                breakdown["total_paise"],
                breakdown["gst_paise"],
                db.dumps(
                    {
                        "plan_id": plan_id,
                        "plan_name": PLANS[plan_id]["name"],
                        "days": PLANS[plan_id]["days"],
                        "applications_per_month": PLANS[plan_id]["applications_per_month"],
                        **breakdown,
                        "gst_rate": GST_RATE,
                    }
                ),
                db.utc_now(),
            ),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="billing.order_created",
            entity_type="payment",
            entity_id=payment_id,
            detail={"plan_id": plan_id, "order_id": order_id},
        )

    return {
        "payment_id": payment_id,
        "order_id": order_id,
        "amount": breakdown["total_paise"],
        "currency": "INR",
        "key_id": RAZORPAY_KEY_ID or "rzp_test_dev",
        "plan_id": plan_id,
        "plan_name": PLANS[plan_id]["name"],
        "breakdown": breakdown,
        "dev_mode": not razorpay_configured(),
    }


def verify_and_activate(
    *,
    user_id: str,
    payment_id: str,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE id = ? AND user_id = ?",
            (payment_id, user_id),
        ).fetchone()
        if not row:
            raise RuntimeError("Payment not found")
        payment = dict(row)

    if razorpay_configured():
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, razorpay_signature):
            raise RuntimeError("Invalid Razorpay signature")
    elif razorpay_signature != "dev_bypass":
        # Local/dev: require explicit bypass token
        raise RuntimeError("Razorpay not configured; use Verify (dev) with signature=dev_bypass")

    with db.connect() as conn:
        conn.execute(
            """
            UPDATE payments SET status = 'paid', razorpay_payment_id = ?, paid_at = ?
            WHERE id = ?
            """,
            (razorpay_payment_id, db.utc_now(), payment_id),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="billing.paid",
            entity_type="payment",
            entity_id=payment_id,
            detail={"razorpay_payment_id": razorpay_payment_id},
        )

    plan = activate_plan(user_id, payment["plan_id"])
    return {"payment": payment, "entitlement": plan}


def handle_webhook(body: bytes, signature: str) -> dict[str, Any]:
    if RAZORPAY_WEBHOOK_SECRET:
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise RuntimeError("Invalid webhook signature")
    event = json.loads(body.decode())
    event_type = event.get("event")
    if event_type == "payment.captured":
        entity = event["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE razorpay_order_id = ?",
                (order_id,),
            ).fetchone()
            if row and row["status"] != "paid":
                conn.execute(
                    """
                    UPDATE payments SET status = 'paid', razorpay_payment_id = ?, paid_at = ?
                    WHERE id = ?
                    """,
                    (entity.get("id"), db.utc_now(), row["id"]),
                )
                activate_plan(row["user_id"], row["plan_id"])
                return {"ok": True, "activated": row["plan_id"]}
    return {"ok": True, "ignored": event_type}


def list_payments(user_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def catalog_for_display() -> list[dict[str, Any]]:
    items = []
    for plan_id, plan in PLANS.items():
        if plan_id == "free":
            continue
        b = plan_price_breakdown(plan_id)
        items.append(
            {
                "plan_id": plan_id,
                **plan,
                "amount_display": f"₹{b['total_paise'] / 100:.0f}",
                "base_display": f"₹{b['base_paise'] / 100:.0f}",
                "gst_display": f"₹{b['gst_paise'] / 100:.0f}",
                "breakdown": b,
            }
        )
    return items
