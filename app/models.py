from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    """One product on one store. `source` + `external_id` identify it uniquely."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_product_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # "daraz", later "amazon", "pickaboo", ...
    external_id: Mapped[str] = mapped_column(String(64))  # e.g. "i123456789-s987654321"
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivery: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)  # standard delivery fee shown on its page
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # the store's category id, e.g. "9543" (phone cases)  # the chosen size/option, e.g. "30 ML Spray"
    currency: Mapped[str] = mapped_column(String(8), default="BDT")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="PriceSnapshot.captured_at"
    )
    market_checks: Mapped[list["MarketCheck"]] = relationship(
        cascade="all, delete-orphan", order_by="MarketCheck.checked_at"
    )


class PriceSnapshot(Base):
    """The price we saw at one moment. Many rows per product = the price history."""

    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_snapshots_product_time", "product_id", "captured_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Numeric(12, 2))  # what you actually pay
    original_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # the crossed-out price
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="snapshots")


class MarketCheck(Base):
    """What other sellers charged for the same product at one moment. Gives a verdict on day one."""

    __tablename__ = "market_checks"
    __table_args__ = (Index("ix_market_product_time", "product_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    query: Mapped[str] = mapped_column(Text)
    seller_count: Mapped[int] = mapped_column(Integer, default=0)
    median_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    low_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    high_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    listings: Mapped[list] = mapped_column(JSON, default=list)
    # False = quick list from search only; True = sellers' pages were opened (sizes, sale prices, delivery)
    detailed: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    """A Telegram price-drop alert. Created on the website, linked to a chat when the
    person presses Start in Telegram (the `token` travels in the t.me link)."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    chat_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    target_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)  # None = any real drop
    baseline_price: Mapped[float] = mapped_column(Numeric(12, 2))  # price when the alert was set
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notified_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    product: Mapped[Product] = relationship()


class Visit(Base):
    """"This browser checked this product." Keeps each visitor's "Recently checked" list private.
    `visitor` is a random id stored in a cookie: no name, no login, nothing personal."""

    __tablename__ = "visits"
    __table_args__ = (UniqueConstraint("visitor", "product_id", name="uq_visit_visitor_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
