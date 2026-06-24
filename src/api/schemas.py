from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProxyCreate(BaseModel):
    host: str
    port: int
    country: str = "RU"
    username: Optional[str] = None
    password: Optional[str] = None
    proxy_type: str = "socks5"


class AccountImport(BaseModel):
    phone: str
    session_file_path: str
    cost_rub: float = 280.0


class ParseChannelRequest(BaseModel):
    channel: str
    limit: int = 500


class ParseKeywordRequest(BaseModel):
    keyword: str
    limit: int = 200


class ABVariantCreate(BaseModel):
    name: str
    outreach_template: str
    system_prompt: str
    bot_link: str
    weight: int = 50


class OutreachConfigCreate(BaseModel):
    name: str = "default"
    message_template: str
    spintax_enabled: bool = True
    typing_simulation: bool = True


class DialogMessageRequest(BaseModel):
    lead_id: int
    message: str
    is_voice: bool = False


class LeadStatusUpdate(BaseModel):
    status: str
    sale_amount_rub: Optional[float] = None


class AccountResponse(BaseModel):
    id: int
    phone: str
    status: str
    phone_country: str
    warmup_day: int
    messages_sent_today: int
    proxy_id: Optional[int]

    model_config = {"from_attributes": True}


class LeadResponse(BaseModel):
    id: int
    tg_user_id: int
    username: Optional[str]
    first_name: Optional[str]
    status: str
    source_type: str
    source_ref: Optional[str]
    retry_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class FunnelResponse(BaseModel):
    period_days: int
    funnel: dict
    economics: dict
    accounts: dict
