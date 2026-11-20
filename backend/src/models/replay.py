from sqlalchemy import Column,Integer,String,Float,JSON,ForeignKey,UniqueConstraint
from src.config.database import Base


class TrialOrder(Base):
    """一条可回放的试印订单。

    `before` / `after` 允许为空：业务现场读数可以未齐。只有两边读数都存在且
    `readings_visible_at` 已到时，该订单才算“已齐读数”。
    """
    __tablename__='trial_orders'
    __table_args__=(UniqueConstraint('study_id','source_key'),)
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    source_key=Column(String(100),nullable=False)
    paper_type=Column(String(120),nullable=False)
    shift=Column(String(120),nullable=False)
    arrived_at=Column(String(40),nullable=False)
    readings_visible_at=Column(String(40),nullable=True)
    before=Column(Float,nullable=True)
    after=Column(Float,nullable=True)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)


class ShiftQuota(Base):
    """每个班次的新工艺名额。回放时随订单一起冻结。"""
    __tablename__='shift_quotas'
    id=Column(Integer,primary_key=True)
    shift=Column(String(120),unique=True,nullable=False)
    quota=Column(Integer,nullable=False)
    updated_at=Column(String(40),nullable=False)


class AllocationReplay(Base):
    """一次名额派单回放。snapshot 冻结当时可见的订单、门槛和班次名额。"""
    __tablename__='replays'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    name=Column(String(120),nullable=False)
    idempotency_key=Column(String(120),unique=True,nullable=False)
    as_of=Column(String(40),nullable=False)
    threshold=Column(Float,nullable=False)
    snapshot=Column(JSON,nullable=False)
    checksum=Column(String(64),nullable=False)
    result=Column(JSON,nullable=False)
    created_at=Column(String(40),nullable=False)
    created_by=Column(String(120),nullable=False)
