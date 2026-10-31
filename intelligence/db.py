from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    quiet_start: Mapped[int | None] = mapped_column(Integer)
    quiet_end: Mapped[int | None] = mapped_column(Integer)
    digest_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Search(Base):
    __tablename__ = "searches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100), default="")
    profile: Mapped[str] = mapped_column(String(40), default="goods")
    params: Mapped[dict[str, str]] = mapped_column(JSON)
    filters_text: Mapped[str] = mapped_column(Text, default="")
    target_model: Mapped[str] = mapped_column(String(120), default="")
    target_memory: Mapped[str] = mapped_column(String(30), default="")
    min_price: Mapped[int | None] = mapped_column(Integer)
    max_price: Mapped[int | None] = mapped_column(Integer)
    seller_filter: Mapped[str] = mapped_column(String(30), default="all")
    condition_filter: Mapped[str] = mapped_column(String(20), default="all")
    notification_mode: Mapped[str] = mapped_column(String(30), default="below_market")
    discount_percent: Mapped[int] = mapped_column(Integer, default=15)
    max_alert_price: Mapped[int | None] = mapped_column(Integer)
    min_score: Mapped[int] = mapped_column(Integer, default=70)
    events_mode: Mapped[str] = mapped_column(String(30), default="new_and_price")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=900)
    status: Mapped[str] = mapped_column(String(30), default="creating")
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    watch_page: Mapped[int] = mapped_column(Integer, default=1)
    watch_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    listings: Mapped[list[Match]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("user_id", "url", name="uq_user_search_url"),)


class Listing(Base):
    __tablename__ = "listings"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    seller_label: Mapped[str] = mapped_column(Text, default="")
    seller_key: Mapped[str] = mapped_column(String(100), default="")
    closed_listings: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    creation_verdict: Mapped[str] = mapped_column(String(24), default="unchecked")
    total_views: Mapped[int | None] = mapped_column(Integer)
    today_views: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Match(Base):
    __tablename__ = "listing_search_matches"
    search_id: Mapped[int] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    state: Mapped[str] = mapped_column(String(30), default="baseline")
    score: Mapped[int | None] = mapped_column(Integer)
    risk: Mapped[int | None] = mapped_column(Integer)
    market_price: Mapped[int | None] = mapped_column(Integer)
    last_price: Mapped[int | None] = mapped_column(Integer)
    exclusion: Mapped[str] = mapped_column(Text, default="")
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    search: Mapped[Search] = relationship(back_populates="listings")
    __table_args__ = (Index("ix_matches_search_state", "search_id", "state"),)


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    event_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("search_id", "listing_id", "event_key"),)


class SavedListing(Base):
    __tablename__ = "saved_listings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    interested: Mapped[bool] = mapped_column(Boolean, default=True)


class ExcludedSeller(Base):
    __tablename__ = "excluded_sellers"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    seller_key: Mapped[str] = mapped_column(
        "seller_label", String(200), primary_key=True
    )


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True
    )
    group_key: Mapped[str] = mapped_column(String(200))
    median: Mapped[int] = mapped_column(Integer)
    low: Mapped[int] = mapped_column(Integer)
    high: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(20))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now
    )


class ImageAnalysis(Base):
    __tablename__ = "image_analysis"
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TextAnalysis(Base):
    __tablename__ = "listing_analysis"
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), default="")
    memory: Mapped[str] = mapped_column(String(30), default="")
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def session_factory(url: str):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30}
        if url.startswith("sqlite")
        else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(engine)
    if url.startswith("sqlite"):
        # The first version was deployed without match-local price. Keep existing data.
        with engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(listing_search_matches)"
                )
            }
            if "last_price" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE listing_search_matches ADD COLUMN last_price INTEGER"
                )
            search_columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(searches)")
            }
            if "watch_page" not in search_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE searches ADD COLUMN watch_page INTEGER DEFAULT 1"
                )
            if "watch_started" not in search_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE searches ADD COLUMN watch_started DATETIME"
                )
            if "failure_count" not in search_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE searches ADD COLUMN failure_count INTEGER DEFAULT 0"
                )
            if "condition_filter" not in search_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE searches ADD COLUMN condition_filter VARCHAR(20) DEFAULT 'all'"
                )
            listing_columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(listings)")
            }
            if "seller_key" not in listing_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE listings ADD COLUMN seller_key VARCHAR(100) DEFAULT ''"
                )
            if "creation_verdict" not in listing_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE listings ADD COLUMN creation_verdict VARCHAR(24) DEFAULT 'unchecked'"
                )
            if "total_views" not in listing_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE listings ADD COLUMN total_views INTEGER"
                )
            if "today_views" not in listing_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE listings ADD COLUMN today_views INTEGER"
                )
            user_columns = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
            }
            if "quiet_start" not in user_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN quiet_start INTEGER"
                )
            if "quiet_end" not in user_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN quiet_end INTEGER"
                )
            if "digest_mode" not in user_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN digest_mode BOOLEAN DEFAULT 0"
                )
            if "last_digest_at" not in user_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE users ADD COLUMN last_digest_at DATETIME"
                )
            connection.exec_driver_sql("PRAGMA user_version=9")
    return sessionmaker(engine, expire_on_commit=False)
