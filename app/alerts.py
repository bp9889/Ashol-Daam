"""Decides when an alert should fire, and writes the messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import telegram
from .models import Alert, Product
from .verdict import money

log = logging.getLogger("asol_dam.alerts")

VERDICT_EMOJI = {"real_deal": "✅", "fair": "➖", "fake_discount": "⚠️", "overpriced": "🏷️", "unconfirmed": "❔"}

ANY_DROP = 0.05  # without a target price, tell people about drops of 5% or more


def describe(alert: Alert) -> str:
    product = alert.product
    title = telegram.escape(product.title)
    if alert.target_price is not None:
        rule = f"when it drops to {money(float(alert.target_price), product.currency)} or less"
    else:
        rule = f"when it drops at least {ANY_DROP:.0%} below {money(float(alert.baseline_price), product.currency)}"
    return f"<b>{title}</b>\nI'll tell you {rule}."


def create(session: Session, product: Product, target_price: float | None) -> Alert:
    if not product.snapshots:
        raise ValueError("This product has no price yet.")
    current = float(product.snapshots[-1].price)
    if target_price is not None and target_price <= 0:
        raise ValueError("The target price has to be more than zero.")
    alert = Alert(
        product_id=product.id,
        token=telegram.new_token(),
        target_price=target_price,
        baseline_price=current,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def should_fire(alert: Alert, price: float) -> bool:
    last = float(alert.last_notified_price) if alert.last_notified_price is not None else None
    if alert.target_price is not None:
        hit = price <= float(alert.target_price)
        return hit and (last is None or price < last)
    dropped = price <= float(alert.baseline_price) * (1 - ANY_DROP)
    return dropped and (last is None or price < last * 0.98)


def check_product(session: Session, product: Product, verdict: dict | None = None) -> int:
    """Called after every new price. Sends the alerts that should fire. Returns how many were sent."""
    if not telegram.enabled() or not product.snapshots:
        return 0
    price = float(product.snapshots[-1].price)
    alerts = session.scalars(
        select(Alert).where(Alert.product_id == product.id, Alert.active.is_(True), Alert.chat_id.is_not(None))
    ).all()

    sent = 0
    for alert in alerts:
        if not should_fire(alert, price):
            continue
        was = float(alert.last_notified_price or alert.baseline_price)
        lines = [
            f"📉 <b>{telegram.escape(product.title)}</b>",
            f"Now {money(price, product.currency)} (was {money(was, product.currency)}).",
        ]
        if verdict:
            # The headline already starts with the verdict ("Real deal. It's 16% below…").
            lines.append(f"{VERDICT_EMOJI.get(verdict['verdict'], '')} {telegram.escape(verdict['headline'])}".strip())
        lines.append(product.url)
        try:
            telegram.send(alert.chat_id, "\n".join(lines))
        except telegram.TelegramError as exc:
            log.warning("Couldn't send alert %s: %s", alert.id, exc)
            if "blocked" in str(exc).lower() or "chat not found" in str(exc).lower():
                alert.active = False  # they blocked the bot; stop trying
            continue
        alert.last_notified_price = price
        alert.last_notified_at = datetime.now(timezone.utc)
        sent += 1
    session.commit()
    return sent
