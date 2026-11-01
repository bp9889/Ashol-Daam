from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import alerts, browser, config, scheduler, services, telegram
from .adapters import AdapterError, BlockedError, PriceNeeded, UnsupportedUrlError, get_adapter
from .db import SessionLocal, get_session, init_db
from .models import Product
from .seed import seed_demo

# Show our own log lines (price checks, alerts) in the terminal next to uvicorn's.
_log = logging.getLogger("asol_dam")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s  %(name)s  %(message)s", "%H:%M:%S"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if config.SEED_DEMO_DATA:
        with SessionLocal() as session:
            seed_demo(session)
    scheduler.start()
    telegram.start_polling()
    yield
    scheduler.stop()
    telegram.stop_polling()


app = FastAPI(title="Asol Dam", version="0.2.0", lifespan=lifespan)


class TrackRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    # Only needed when the store doesn't publish the price of the chosen size/option.
    price: float | None = Field(default=None, gt=0, lt=100_000_000)


class AlertRequest(BaseModel):
    target_price: float | None = Field(default=None, gt=0, lt=100_000_000)


@app.exception_handler(AdapterError)
async def adapter_error_handler(_, exc: AdapterError):
    if isinstance(exc, PriceNeeded):
        return JSONResponse(status_code=422, content={
            "detail": str(exc), "need_price": True, "variant": exc.variant, "old_price": exc.old_price})
    status = 503 if isinstance(exc, BlockedError) else 400 if isinstance(exc, UnsupportedUrlError) else 502
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.post("/api/track")
def track(body: TrackRequest, session: Session = Depends(get_session)):
    product = services.track(session, body.url, body.price)
    return services.report(product)


@app.get("/api/products")
def list_products(session: Session = Depends(get_session)):
    products = session.scalars(select(Product).order_by(Product.is_demo, Product.last_checked_at.desc())).all()
    return [services.summary(p) for p in products]


def _get(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="We aren't tracking that product.")
    return product


@app.get("/api/products/{product_id}")
def get_product(product_id: int, session: Session = Depends(get_session)):
    product = _get(session, product_id)
    if not product.is_demo and services.market_outdated(product):
        # Seller list saved with older rules (e.g. before photos): rebuild it now. One search request.
        services.update_market(session, product, get_adapter(product.url))
    return services.report(product)


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, session: Session = Depends(get_session)):
    product = _get(session, product_id)
    if product.is_demo:
        raise HTTPException(status_code=400, detail="Sample products can't be removed. Set SEED_DEMO_DATA=0 to hide them.")
    session.delete(product)
    session.commit()
    return {"ok": True}


@app.post("/api/products/{product_id}/refresh")
def refresh_product(product_id: int, session: Session = Depends(get_session)):
    return services.report(services.refresh(session, _get(session, product_id)))


# ---- Phase 2 ---------------------------------------------------------------


@app.get("/api/status")
def status():
    return {
        "alerts_enabled": telegram.enabled(),
        "check_times": config.CHECK_TIMES,
        "timezone": config.TIMEZONE,
        "scheduler": scheduler.state,
        "browser": browser.status(),
    }


@app.post("/api/products/{product_id}/alerts")
def create_alert(product_id: int, body: AlertRequest, session: Session = Depends(get_session)):
    if not telegram.enabled():
        raise HTTPException(status_code=503, detail="Telegram alerts aren't set up on this site yet.")
    product = _get(session, product_id)
    if product.is_demo:
        raise HTTPException(status_code=400, detail="Alerts only work on real products, not samples.")
    try:
        alert = alerts.create(session, product, body.target_price)
        link = telegram.start_link(alert.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except telegram.TelegramError as exc:
        raise HTTPException(status_code=502, detail="Couldn't reach Telegram. Try again in a minute.") from exc
    return {"link": link, "target_price": alert.target_price, "baseline_price": float(alert.baseline_price)}


@app.post("/api/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    expected = config.TELEGRAM_WEBHOOK_SECRET
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=404)
    update = await request.json()
    with SessionLocal() as session:
        try:
            telegram.handle_update(session, update)
        except telegram.TelegramError as exc:
            logging.getLogger("asol_dam.telegram").warning("Webhook reply failed: %s", exc)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


# The website itself. Mounted last so /api routes win.
app.mount("/", StaticFiles(directory=config.BASE_DIR / "static", html=True), name="static")
