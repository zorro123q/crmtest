"""
SQLAlchemy ORM models.
"""
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
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


def uuid_str() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=uuid_str)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=False)
    hashed_pwd = Column(String(255), nullable=False)
    role = Column(Enum("admin", "manager", "sales", name="user_role"), nullable=False, default="sales")
    avatar_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    # JSON 字段：存储用户可访问的模块列表，null 表示按角色默认权限
    permissions = Column(JSON, default=None)

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
    status = Column(
        Enum("New", "Working", "Nurturing", "Converted", "Disqualified", name="lead_status"),
        default="New",
    )
    score = Column(SmallInteger, default=0)
    owner_id = Column(String(36), ForeignKey("users.id"))
    converted_to = Column(String(36))
    custom_fields = Column(JSON, default=dict)
    ai_extracted = Column(JSON, default=dict)

    owner = relationship("User", back_populates="leads")


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"

    id = Column(String(36), primary_key=True, default=uuid_str)
    name = Column(String(500), nullable=False)
    account_id = Column(String(36), ForeignKey("accounts.id"))
    contact_id = Column(String(36), ForeignKey("contacts.id"))
    owner_id = Column(String(36), ForeignKey("users.id"))

    stage = Column(
        Enum("初步接触", "方案报价", "合同谈判", "赢单", "输单", name="opp_stage"),
        nullable=False,
        default="初步接触",
    )
    amount = Column(Numeric(15, 2))
    probability = Column(SmallInteger, default=20)
    close_date = Column(Date)
    source = Column(String(100))

    ai_confidence = Column(Numeric(4, 3))
    ai_raw_text = Column(Text)
    ai_extracted = Column(JSON, default=dict)
    custom_fields = Column(JSON, default=dict)
    stage_history = Column(JSON, default=list)
    closed_at = Column(DateTime(timezone=True))

    owner = relationship("User", back_populates="opportunities", foreign_keys=[owner_id])
    account = relationship("Account", back_populates="opportunities")
    contact = relationship("Contact", foreign_keys=[contact_id])


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
