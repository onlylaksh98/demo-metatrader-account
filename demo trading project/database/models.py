import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, String, Float, DateTime, Integer, Boolean, BigInteger, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, sessionmaker, relationship

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///telegram2mt5.db")


class Base(DeclarativeBase):
    pass


class Message(Base):
    """Raw Telegram messages captured from the VIP channel."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(String, nullable=False)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    entry_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    take_profits: Mapped[list["SignalTakeProfit"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan", lazy="joined"
    )
    versions: Mapped[list["SignalVersion"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )
    events: Mapped[list["SignalEvent"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )


class SignalTakeProfit(Base):
    __tablename__ = "signal_take_profits"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    hit: Mapped[bool] = mapped_column(Boolean, default=False)

    signal: Mapped["Signal"] = relationship(back_populates="take_profits")


class SignalVersion(Base):
    __tablename__ = "signal_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    entry_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped["Signal"] = relationship(back_populates="versions")


class SignalEvent(Base):
    __tablename__ = "signal_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped["Signal"] = relationship(back_populates="events")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(10))
    volume: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mt5_ticket: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mt5_order_ticket: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
