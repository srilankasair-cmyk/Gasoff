"""Pydantic schemas for API requests, responses, and internal data."""

from pydantic import BaseModel, Field
from typing import Optional


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class TelegramChat(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    username: Optional[str] = None


class SuccessfulPayment(BaseModel):
    currency: str
    total_amount: int
    invoice_payload: str
    telegram_payment_charge_id: str
    provider_payment_charge_id: str


class TelegramMessage(BaseModel):
    message_id: int
    from_user: Optional[TelegramUser] = Field(None, alias="from")
    chat: TelegramChat
    text: Optional[str] = None
    date: int
    forward_from: Optional[TelegramUser] = None
    forward_sender_name: Optional[str] = None
    successful_payment: Optional[SuccessfulPayment] = None

    class Config:
        populate_by_name = True


class PreCheckoutQuery(BaseModel):
    id: str
    from_user: TelegramUser = Field(alias="from")
    currency: str
    total_amount: int
    invoice_payload: str

    class Config:
        populate_by_name = True



class CallbackQuery(BaseModel):
    id: str
    from_user: TelegramUser = Field(alias="from")
    data: Optional[str] = None
    message: Optional[TelegramMessage] = None

    class Config:
        populate_by_name = True


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
    callback_query: Optional[CallbackQuery] = None
    pre_checkout_query: Optional[PreCheckoutQuery] = None


class DeidentifiedSegment(BaseModel):
    original: str
    placeholder: str
    type: str


class DeidentificationResult(BaseModel):
    clean_text: str
    segments: list[DeidentifiedSegment]


class GottmanScores(BaseModel):
    criticism: float = Field(..., ge=0, le=100)
    contempt: float = Field(..., ge=0, le=100)
    defensiveness: float = Field(..., ge=0, le=100)
    stonewalling: float = Field(..., ge=0, le=100)


class GottmanData(BaseModel):
    user: GottmanScores
    other: GottmanScores


class CircumplexAxis(BaseModel):
    dominance: float = Field(0, ge=-100, le=100)
    arrogance: float = Field(0, ge=-100, le=100)
    coldness: float = Field(0, ge=-100, le=100)
    hostility: float = Field(0, ge=-100, le=100)
    submission: float = Field(0, ge=-100, le=100)
    humility: float = Field(0, ge=-100, le=100)
    warmth: float = Field(0, ge=-100, le=100)
    empathy: float = Field(0, ge=-100, le=100)


class CircumplexData(BaseModel):
    user: CircumplexAxis
    other: CircumplexAxis


class ToxicSentence(BaseModel):
    sentence: str
    label: str
    explanation: str
    original_speaker: str
    counter_suggestion: str


class AnalysisResult(BaseModel):
    other_name: str
    toxicity_score: float
    toxicity_direction: str = "other_to_self"
    toxicity_explanation: str = ""
    gottman: GottmanData
    circumplex: CircumplexData
    toxic_sentences: list[ToxicSentence]
    summary: str
