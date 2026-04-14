"""
Pydantic Schemas（请求/响应数据验证）
"""
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator, validator


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    role: str
    avatar_url: Optional[str] = None
    permissions: Optional[Dict[str, Any]] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    """管理员创建用户"""
    username: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=1)
    role: str = "sales"
    permissions: Optional[Dict[str, bool]] = None


class UserUpdateRequest(BaseModel):
    """管理员更新用户"""
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    permissions: Optional[Dict[str, bool]] = None
    is_active: Optional[bool] = None


class UserPasswordReset(BaseModel):
    """重置用户密码"""
    new_password: str = Field(..., min_length=1)


# ─────────────────────────────────────────────
# Opportunity
# ─────────────────────────────────────────────
class OpportunityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    account_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    stage: str = "初步接洽"
    amount: Optional[float] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    close_date: Optional[date] = None
    source: Optional[str] = None
    ai_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ai_raw_text: Optional[str] = None
    ai_extracted: Optional[Dict[str, Any]] = None
    custom_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)


class OpportunityUpdate(BaseModel):
    name: Optional[str] = None
    stage: Optional[str] = None
    amount: Optional[float] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    close_date: Optional[date] = None
    source: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class OpportunityOut(BaseModel):
    id: UUID
    name: str
    stage: str
    amount: Optional[float] = None
    probability: Optional[int] = None
    close_date: Optional[date] = None
    source: Optional[str] = None
    ai_confidence: Optional[float] = None
    custom_fields: Dict[str, Any] = {}
    stage_history: List[Dict] = []
    owner: Optional[UserOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StageMoveRequest(BaseModel):
    """看板拖拽：更新商机阶段"""
    stage: str
    opp_id: UUID


# ─────────────────────────────────────────────
# Lead
# ─────────────────────────────────────────────
class LeadCreate(BaseModel):
    name: str
    company: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str = "New"
    score: Optional[int] = Field(0, ge=0, le=100)
    custom_fields: Optional[Dict[str, Any]] = Field(default_factory=dict)


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    score: Optional[int] = Field(None, ge=0, le=100)
    custom_fields: Optional[Dict[str, Any]] = None


class LeadOut(BaseModel):
    id: UUID
    name: str
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str
    score: int = 0
    owner_id: Optional[UUID] = None
    custom_fields: Dict[str, Any] = {}
    owner: Optional[UserOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# AI
# ─────────────────────────────────────────────
class AIParseRequest(BaseModel):
    text: str = Field(..., min_length=5, description="原始语音转写文本")
    save_to_opportunity: bool = Field(False, description="解析后是否直接创建商机")


class AIParseResponse(BaseModel):
    customer_name: str
    deal_value: float
    stage: str
    key_needs: List[str]
    next_step: str
    confidence_score: float
    usage: Optional[Dict[str, Any]] = None
    opportunity_id: Optional[UUID] = None   # 若 save_to_opportunity=True


# ─────────────────────────────────────────────
# 通用分页
# ─────────────────────────────────────────────
class CardEvaluateRequest(BaseModel):
    card_type: Literal["A", "B"]
    company: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    opportunity_name: Optional[str] = Field(None, max_length=255)
    amount: Optional[float] = Field(None, ge=0)
    text: str = Field("", max_length=10000)

    @model_validator(mode="after")
    def validate_inputs(self):
        if self.card_type == "A" and not ((self.company or "").strip() or self.text.strip()):
            raise ValueError("A 卡至少需要客户名称或描述文本")
        if self.card_type == "B" and not (
            (self.company or "").strip() or (self.opportunity_name or "").strip() or self.text.strip()
        ):
            raise ValueError("B 卡至少需要客户名称、商机名称或描述文本")
        return self


class CardDimensionScore(BaseModel):
    key: str
    name: str
    score: int
    max_score: int


class CardEvaluateResponse(BaseModel):
    card_type: Literal["A", "B"]
    normalized_score: int
    raw_score: int
    raw_max_score: int
    grade: str
    grade_label: str
    rating_desc: str
    suggestion: str
    dimensions: List[CardDimensionScore]


class CardTranscribeResponse(BaseModel):
    text: str
    duration_hint: str


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    data: List[Any]
