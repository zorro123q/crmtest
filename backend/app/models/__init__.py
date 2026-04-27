"""
SQLAlchemy ORM models.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.services.crm_rules_service import DEFAULT_OPPORTUNITY_STAGE


def uuid_str() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=uuid_str)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)

    opportunities = relationship("Opportunity", back_populates="owner", foreign_keys="Opportunity.owner_id")
    leads = relationship("Lead", back_populates="owner")


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=uuid_str)
    name = Column(String(255), nullable=False)
    industry = Column(String(100))
    size = Column(String(50))
    annual_revenue = Column(Numeric(15, 2))
    website = Column(String(500))
    owner_id = Column(String(36), ForeignKey("users.id"))
    custom_fields = Column(JSON, default=dict)

    owner = relationship("User", foreign_keys=[owner_id])
    opportunities = relationship("Opportunity", back_populates="account")
    contacts = relationship("Contact", back_populates="account")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=uuid_str)
    name = Column(String(255), nullable=False)
    title = Column(String(200))
    email = Column(String(255))
    phone = Column(String(50))
    account_id = Column(String(36), ForeignKey("accounts.id"))
    owner_id = Column(String(36), ForeignKey("users.id"))
    custom_fields = Column(JSON, default=dict)

    account = relationship("Account", back_populates="contacts")
    owner = relationship("User", foreign_keys=[owner_id])


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True, default=uuid_str)
    name = Column(String(255), nullable=False)
    company = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    source = Column(String(100))
    status = Column(String(50), nullable=False, default="new")
    score = Column(SmallInteger, default=0)
    card_score = Column(Integer, nullable=False, default=0)
    card_level = Column(String(1), nullable=False, default="E")
    owner_id = Column(String(36), ForeignKey("users.id"))
    converted_to = Column(String(36))
    is_active = Column(Boolean, nullable=False, default=True)

    industry = Column(String(100))
    industry_rank = Column(String(100))
    scene = Column(String(120))
    budget = Column(String(100))
    labor_cost = Column(String(100))
    daily_calls = Column(String(100))
    leader_owner = Column(String(100))
    lowest_price = Column(String(50))
    initiator_department = Column(String(100))
    competitor = Column(String(100))
    bidding_type = Column(String(100))
    has_ai_project = Column(String(50))
    customer_service_size = Column(String(100))
    region = Column(String(100))

    score_detail_json = Column(JSON, default=dict)
    custom_fields = Column(JSON, default=dict)
    ai_extracted = Column(JSON, default=dict)

    owner = relationship("User", back_populates="leads")

    @property
    def owner_username(self) -> str | None:
        return self.owner.username if self.owner else None


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"

    id = Column(String(36), primary_key=True, default=uuid_str)
    name = Column(String(500), nullable=False)
    account_id = Column(String(36), ForeignKey("accounts.id"))
    contact_id = Column(String(36), ForeignKey("contacts.id"))
    owner_id = Column(String(36), ForeignKey("users.id"))

    stage = Column(String(100), nullable=False, default=DEFAULT_OPPORTUNITY_STAGE)
    status = Column(String(50), nullable=False, default="new")
    amount = Column(Numeric(15, 2))
    probability = Column(SmallInteger, default=20)
    close_date = Column(Date)
    source = Column(String(100))

    card_score = Column(Integer, nullable=False, default=0)
    card_level = Column(String(1), nullable=False, default="E")
    is_active = Column(Boolean, nullable=False, default=True)

    industry = Column(String(100))
    industry_rank = Column(String(100))
    scene = Column(String(120))
    budget = Column(String(100))
    labor_cost = Column(String(100))
    daily_calls = Column(String(100))
    leader_owner = Column(String(100))
    lowest_price = Column(String(50))
    initiator_department = Column(String(100))
    competitor = Column(String(100))
    bidding_type = Column(String(100))
    has_ai_project = Column(String(50))
    customer_service_size = Column(String(100))
    region = Column(String(100))

    # 客户商机管理表正式业务字段
    customer_name = Column(String(255), index=True)
    customer_type = Column(String(50))
    requirement_desc = Column(Text)
    product_name = Column(String(255))
    estimated_cycle = Column(String(100))
    opportunity_level = Column(String(10))
    project_date = Column(String(100))
    project_members = Column(Text)
    solution_communication = Column(Text)
    poc_status = Column(Text)
    key_person_approved = Column(String(20))
    bid_probability = Column(String(10))
    contract_negotiation = Column(Text)
    project_type = Column(String(100))
    contract_signed = Column(String(20))
    handoff_completed = Column(String(20))

    ai_confidence = Column(Numeric(4, 3))
    ai_raw_text = Column(Text)
    ai_extracted = Column(JSON, default=dict)
    custom_fields = Column(JSON, default=dict)
    score_detail_json = Column(JSON, default=dict)
    stage_history = Column(JSON, default=list)
    closed_at = Column(DateTime(timezone=True))

    owner = relationship("User", back_populates="opportunities", foreign_keys=[owner_id])
    account = relationship("Account", back_populates="opportunities")
    contact = relationship("Contact", foreign_keys=[contact_id])

    @property
    def owner_username(self) -> str | None:
        return self.owner.username if self.owner else None


class Activity(Base):
    __tablename__ = "activities"

    id = Column(String(36), primary_key=True, default=uuid_str)
    type = Column(String(50), nullable=False)
    subject = Column(String(500))
    description = Column(Text)
    owner_id = Column(String(36), ForeignKey("users.id"))
    opp_id = Column(String(36), ForeignKey("opportunities.id", ondelete="CASCADE"))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"))
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"))
    due_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    custom_fields = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", foreign_keys=[owner_id])


class MetadataField(Base):
    __tablename__ = "metadata_fields"

    id = Column(String(36), primary_key=True, default=uuid_str)
    object_name = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=False)
    display_name = Column(String(200), nullable=False)
    field_type = Column(String(50), nullable=False)
    options = Column(JSON)
    is_required = Column(Boolean, default=False)
    is_visible = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())