"""
Pydantic schemas.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.services.crm_rules_service import (
    DEFAULT_OPPORTUNITY_STAGE,
    LEAD_STATUSES,
    OPPORTUNITY_STATUSES,
    STAGE_ORDER,
    normalize_lead_status,
    normalize_opportunity_stage,
)
from app.services.scoring_service import SCORING_FIELD_KEYS, is_valid_option


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    is_admin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=255)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(None, min_length=1, max_length=100)
    password: str | None = Field(None, min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=255)
    new_password: str = Field(..., min_length=1, max_length=255)
    confirm_password: str = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_passwords(self):
        if not self.current_password.strip():
            raise ValueError("Current password is required")
        if not self.new_password.strip():
            raise ValueError("New password is required")
        if not self.confirm_password.strip():
            raise ValueError("Please confirm the new password")
        if self.new_password != self.confirm_password:
            raise ValueError("The two new passwords do not match")
        return self


class MessageResponse(BaseModel):
    message: str


class ScoringDimensionsInput(BaseModel):
    industry: str | None = None
    industry_rank: str | None = None
    scene: str | None = None
    budget: str | None = None
    labor_cost: str | None = None
    daily_calls: str | None = None
    leader_owner: str | None = None
    lowest_price: str | None = None
    initiator_department: str | None = None
    competitor: str | None = None
    bidding_type: str | None = None
    has_ai_project: str | None = None
    customer_service_size: str | None = None
    region: str | None = None

    @model_validator(mode="after")
    def validate_scoring_dimensions(self):
        for field_name in SCORING_FIELD_KEYS:
            value = getattr(self, field_name)
            if not is_valid_option(field_name, value):
                raise ValueError(f"Invalid scoring option for {field_name}: {value}")
        return self

    def to_dimensions_dict(self) -> dict[str, str | None]:
        return {field_name: getattr(self, field_name) for field_name in SCORING_FIELD_KEYS}

    def has_any_value(self) -> bool:
        return any(getattr(self, field_name) not in (None, "") for field_name in SCORING_FIELD_KEYS)


class OpportunityCreate(ScoringDimensionsInput):
    name: str | None = Field(None, min_length=1, max_length=500)
    account_id: UUID | None = None
    contact_id: UUID | None = None
    stage: str = DEFAULT_OPPORTUNITY_STAGE
    status: str | None = "new"
    amount: float | None = None
    probability: int | None = Field(None, ge=0, le=100)
    close_date: date | None = None
    source: str | None = None
    ai_confidence: float | None = Field(None, ge=0.0, le=1.0)
    ai_raw_text: str | None = None
    ai_extracted: dict[str, Any] | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    # 客户商机管理表字段
    customer_name: str | None = Field(None, max_length=255)
    customer_type: str | None = Field(None, max_length=50)
    requirement_desc: str | None = None
    product_name: str | None = Field(None, max_length=255)
    estimated_cycle: str | None = Field(None, max_length=100)
    opportunity_level: str | None = Field(None, max_length=10)
    project_date: str | None = Field(None, max_length=100)
    project_members: str | None = None
    solution_communication: str | None = None
    poc_status: str | None = None
    key_person_approved: str | None = Field(None, max_length=20)
    bid_probability: str | None = Field(None, max_length=10)
    contract_negotiation: str | None = None
    project_type: str | None = Field(None, max_length=100)
    contract_signed: str | None = Field(None, max_length=20)
    handoff_completed: str | None = Field(None, max_length=20)

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str):
        return normalize_opportunity_stage(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None):
        normalized = str(value or "").strip().lower() or "new"
        if normalized not in OPPORTUNITY_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(OPPORTUNITY_STATUSES)}")
        return normalized

    @model_validator(mode="after")
    def validate_business_identity(self):
        if not ((self.name or "").strip() or (self.customer_name or "").strip()):
            raise ValueError("Either name or customer_name is required")
        return self


class OpportunityUpdate(ScoringDimensionsInput):
    name: str | None = None
    stage: str | None = None
    status: str | None = None
    amount: float | None = None
    probability: int | None = Field(None, ge=0, le=100)
    close_date: date | None = None
    source: str | None = None
    custom_fields: dict[str, Any] | None = None

    # 客户商机管理表字段
    customer_name: str | None = Field(None, max_length=255)
    customer_type: str | None = Field(None, max_length=50)
    requirement_desc: str | None = None
    product_name: str | None = Field(None, max_length=255)
    estimated_cycle: str | None = Field(None, max_length=100)
    opportunity_level: str | None = Field(None, max_length=10)
    project_date: str | None = Field(None, max_length=100)
    project_members: str | None = None
    solution_communication: str | None = None
    poc_status: str | None = None
    key_person_approved: str | None = Field(None, max_length=20)
    bid_probability: str | None = Field(None, max_length=10)
    contract_negotiation: str | None = None
    project_type: str | None = Field(None, max_length=100)
    contract_signed: str | None = Field(None, max_length=20)
    handoff_completed: str | None = Field(None, max_length=20)

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str | None):
        if value is None:
            return value
        return normalize_opportunity_stage(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None):
        if value is None:
            return value
        normalized = str(value).strip().lower()
        if normalized not in OPPORTUNITY_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(OPPORTUNITY_STATUSES)}")
        return normalized


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    stage: str
    status: str
    amount: float | None = None
    probability: int | None = None
    close_date: date | None = None
    source: str | None = None
    card_score: int = 0
    card_level: str = "E"

    industry: str | None = None
    industry_rank: str | None = None
    scene: str | None = None
    budget: str | None = None
    labor_cost: str | None = None
    daily_calls: str | None = None
    leader_owner: str | None = None
    lowest_price: str | None = None
    initiator_department: str | None = None
    competitor: str | None = None
    bidding_type: str | None = None
    has_ai_project: str | None = None
    customer_service_size: str | None = None
    region: str | None = None

    # 客户商机管理表字段
    customer_name: str | None = None
    customer_type: str | None = None
    requirement_desc: str | None = None
    product_name: str | None = None
    estimated_cycle: str | None = None
    opportunity_level: str | None = None
    project_date: str | None = None
    project_members: str | None = None
    solution_communication: str | None = None
    poc_status: str | None = None
    key_person_approved: str | None = None
    bid_probability: str | None = None
    contract_negotiation: str | None = None
    project_type: str | None = None
    contract_signed: str | None = None
    handoff_completed: str | None = None

    score_detail_json: dict[str, Any] = Field(default_factory=dict)
    ai_confidence: float | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    stage_history: list[dict[str, Any]] = Field(default_factory=list)
    owner_id: UUID | None = None
    owner_username: str | None = None
    owner: UserOut | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
########
class StageMoveRequest(BaseModel):
    stage: str
    opp_id: UUID

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str):
        return normalize_opportunity_stage(value)


class LeadCreate(ScoringDimensionsInput):
    name: str = Field(..., min_length=1, max_length=255)
    company: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=100)
    status: str = "new"
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        return normalize_lead_status(value)


class LeadUpdate(ScoringDimensionsInput):
    name: str | None = None
    company: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=100)
    status: str | None = None
    custom_fields: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None):
        if value is None:
            return value
        return normalize_lead_status(value)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    status: str
    score: int = 0
    card_score: int = 0
    card_level: str = "E"
    industry: str | None = None
    industry_rank: str | None = None
    scene: str | None = None
    budget: str | None = None
    labor_cost: str | None = None
    daily_calls: str | None = None
    leader_owner: str | None = None
    lowest_price: str | None = None
    initiator_department: str | None = None
    competitor: str | None = None
    bidding_type: str | None = None
    has_ai_project: str | None = None
    customer_service_size: str | None = None
    region: str | None = None
    score_detail_json: dict[str, Any] = Field(default_factory=dict)
    owner_id: UUID | None = None
    owner_username: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    owner: UserOut | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class OpportunityReportSummary(BaseModel):
    owner_id: UUID | None = None
    owner_username: str
    total_count: int = 0
    following_count: int = 0
    won_count: int = 0
    high_priority_count: int = 0
    this_week_new: int = 0
    this_month_new: int = 0


class OpportunityReportResponse(BaseModel):
    scope: Literal["me", "user", "all"]
    summary: OpportunityReportSummary
    reports: list[OpportunityReportSummary] = Field(default_factory=list)


class AIParseRequest(BaseModel):
    text: str = Field(..., min_length=5, description="Original transcript or note")
    save_to_opportunity: bool = Field(False, description="Create an opportunity after parsing")


class AIParseResponse(BaseModel):
    customer_name: str
    deal_value: float
    stage: str
    key_needs: list[str]
    next_step: str
    confidence_score: float
    usage: dict[str, Any] | None = None
    opportunity_id: UUID | None = None


class CardEvaluateRequest(BaseModel):
    card_type: Literal["A", "B"]
    company: str | None = Field(None, max_length=255)
    industry: str | None = Field(None, max_length=100)
    opportunity_name: str | None = Field(None, max_length=255)
    amount: float | None = Field(None, ge=0)
    analysis_mode: Literal["ai", "manual", "hybrid"] = "hybrid"
    ai_dimensions: dict[str, str | None] | None = None
    manual_dimensions: dict[str, str | None] | None = None
    text: str = Field("", max_length=10000)

    @model_validator(mode="after")
    def validate_inputs(self):
        has_text = bool(self.text.strip())
        has_ai_dimensions = _dimensions_have_any_value(self.ai_dimensions)
        has_manual_dimensions = _dimensions_have_any_value(self.manual_dimensions)

        if self.analysis_mode == "manual":
            if not has_manual_dimensions:
                raise ValueError("manual mode requires at least one manual dimension")
            return self

        if self.analysis_mode == "ai":
            if not has_text:
                raise ValueError("ai mode requires text")
            return self

        if not has_manual_dimensions and not has_ai_dimensions and not has_text:
            raise ValueError("hybrid mode requires manual dimensions or AI input")
        if not has_ai_dimensions and not has_text:
            raise ValueError("hybrid mode requires text when ai_dimensions is not provided")
        return self


class CardDimensionScore(BaseModel):
    key: str
    name: str
    score: int | float
    max_score: int | float
    selected_value: str | None = None
    selected_label: str | None = None
    source: Literal["manual", "ai", "none"]


class CardEvaluateResponse(BaseModel):
    card_type: Literal["A", "B"]
    normalized_score: int | float
    raw_score: int | float
    raw_max_score: int | float
    grade: str
    grade_label: str
    rating_desc: str
    suggestion: str
    ai_dimensions: dict[str, str | None] | None = None
    manual_dimensions: dict[str, str | None] | None = None
    merged_dimensions: dict[str, str | None]
    dimensions: list[CardDimensionScore]


class CardTranscribeResponse(BaseModel):
    text: str
    duration_hint: str


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    data: list[Any]


def _dimensions_have_any_value(dimensions: dict[str, str | None] | None) -> bool:
    if not dimensions:
        return False
    return any(value not in (None, "") for value in dimensions.values())
