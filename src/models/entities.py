import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    IMPORTED = "imported"
    PROXY_BOUND = "proxy_bound"
    PROFILE_PENDING = "profile_pending"
    WARMING = "warming"
    READY = "ready"
    ACTIVE = "active"
    QUARANTINE = "quarantine"
    SPAM_PAUSED = "spam_paused"
    DEAD = "dead"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    WRITTEN = "written"
    REPLIED = "replied"
    IN_BOT = "in_bot"
    APPLICATION = "application"
    CALL = "call"
    SALE = "sale"
    LOST = "lost"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    SPAM = "spam"
    FAILED = "failed"
    RETRY = "retry"


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="RU")
    proxy_type: Mapped[str] = mapped_column(String(16), default="socks5")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["Account"]] = relationship(back_populates="proxy")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    session_path: Mapped[str] = mapped_column(String(512))
    phone_country: Mapped[str] = mapped_column(String(2), default="RU")
    status: Mapped[AccountStatus] = mapped_column(Enum(AccountStatus), default=AccountStatus.IMPORTED)
    proxy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("proxies.id"), nullable=True)

    first_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    birth_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    avatar_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    profile_scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    story_posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    warmup_day: Mapped[int] = mapped_column(Integer, default=0)
    warmup_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    warmup_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    messages_sent_today: Mapped[int] = mapped_column(Integer, default=0)
    daily_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    cost_rub: Mapped[float] = mapped_column(Float, default=280.0)
    died_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    proxy: Mapped[Optional["Proxy"]] = relationship(back_populates="accounts")
    outreach_messages: Mapped[list["OutreachMessage"]] = relationship(back_populates="account")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tg_user_id", name="uq_lead_tg_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="channel")
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.NEW)
    ab_variant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ab_variants.id"), nullable=True)
    assigned_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    application_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    call_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sale_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sale_amount_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["OutreachMessage"]] = relationship(back_populates="lead")
    dialog_messages: Mapped[list["DialogMessage"]] = relationship(back_populates="lead")
    ab_variant: Mapped[Optional["ABVariant"]] = relationship(back_populates="leads")


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    text: Mapped[str] = mapped_column(Text)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.PENDING
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="messages")
    account: Mapped["Account"] = relationship(back_populates="outreach_messages")


class DialogMessage(Base):
    __tablename__ = "dialog_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    is_voice_transcript: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lead: Mapped["Lead"] = relationship(back_populates="dialog_messages")


class ABVariant(Base):
    __tablename__ = "ab_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    outreach_template: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    bot_link: Mapped[str] = mapped_column(String(512))
    weight: Mapped[int] = mapped_column(Integer, default=50)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    leads: Mapped[list["Lead"]] = relationship(back_populates="ab_variant")


class ParseJob(Base):
    __tablename__ = "parse_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(255))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    leads_found: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class FunnelEvent(Base):
    __tablename__ = "funnel_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cost_rub: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SalesHandoff(Base):
    __tablename__ = "sales_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"))
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    first_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sla_deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutreachConfig(Base):
    __tablename__ = "outreach_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="default")
    message_template: Mapped[str] = mapped_column(Text)
    spintax_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    typing_simulation: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
