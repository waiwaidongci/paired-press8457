import math
from typing import Optional
from pydantic import BaseModel,Field,field_validator
from src.utils.timeutil import parse_timestamp


def _distance(value,label):
    if value is None: return None
    if isinstance(value,bool): raise ValueError(label+'必须是数值')
    try: number=float(value)
    except (TypeError,ValueError): raise ValueError(label+'必须是数值')
    if not math.isfinite(number) or number<0 or number>1e9:
        raise ValueError(label+'必须是 0 到 1e9 的有限业务数值')
    return number


class TrialOrderInput(BaseModel):
    source_key:str=Field(min_length=1,max_length=100)
    paper_type:str=Field(min_length=1,max_length=120)
    shift:str=Field(min_length=1,max_length=120)
    arrived_at:str=Field(min_length=1,max_length=40)
    readings_visible_at:Optional[str]=Field(default=None,max_length=40)
    before:Optional[float]=None
    after:Optional[float]=None

    @field_validator('source_key','paper_type','shift')
    @classmethod
    def _strip(cls,value):
        value=value.strip()
        if not value: raise ValueError('字段不能为空')
        return value

    @field_validator('arrived_at')
    @classmethod
    def _arrived(cls,value):
        parsed=parse_timestamp(value,'到单时刻')
        if parsed is None: raise ValueError('到单时刻不能为空')
        return parsed

    @field_validator('readings_visible_at')
    @classmethod
    def _visible(cls,value):
        return parse_timestamp(value,'读数可见时刻')

    @field_validator('before','after')
    @classmethod
    def _reading(cls,value):
        return _distance(value,'色差读数')


class ShiftQuotaInput(BaseModel):
    quota:int=Field(ge=0,le=100000)


class ReplayInput(BaseModel):
    study_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    as_of:Optional[str]=Field(default=None,max_length=40)
    threshold:float
    idempotency_key:str=Field(min_length=1,max_length=120)

    @field_validator('idempotency_key')
    @classmethod
    def _key(cls,value):
        value=value.strip()
        if not value: raise ValueError('幂等键不能为空')
        return value

    @field_validator('threshold')
    @classmethod
    def _threshold(cls,value):
        if isinstance(value,bool): raise ValueError('门槛必须是数值')
        number=float(value)
        if not math.isfinite(number): raise ValueError('门槛必须是有限数值')
        return number

    @field_validator('as_of')
    @classmethod
    def _as_of(cls,value):
        return parse_timestamp(value,'回放时刻')
