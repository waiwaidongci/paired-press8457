import csv, io
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.database import Session, engine
from src.models.replay import TrialOrder, ShiftQuota, AllocationReplay
from src.services import studies
from src.services.replay_algorithm import simulate, _order_key
from src.services.audits import log
from src.utils.serializers import record, now, checksum
from src.utils.timeutil import parse_timestamp


def _order_dict(row):
    # 读取时再次规范化，保证可直接按字符串比较时间；兼容早期直接写入的记录。
    return {
        'id': row.id,
        'source_key': row.source_key,
        'paper_type': row.paper_type,
        'shift': row.shift,
        'arrived_at': parse_timestamp(row.arrived_at, '到单时刻'),
        'readings_visible_at': parse_timestamp(row.readings_visible_at, '读数可见时刻'),
        'before': row.before,
        'after': row.after,
    }


def list_orders(db, study_id):
    studies.require(db, study_id)
    items = [_order_dict(x) for x in db.scalars(
        select(TrialOrder).where(TrialOrder.study_id == study_id)
    )]
    return sorted(items, key=_order_key)


def _validate_readings(data):
    if data.before is not None and data.after is not None and data.readings_visible_at is None:
        raise ValueError('成对读数已齐时必须记录读数可见时刻')
    if data.readings_visible_at is not None and data.readings_visible_at < data.arrived_at:
        raise ValueError('读数可见时刻不能早于到单时刻')


def save_order(db, study_id, data, user, row_id=None):
    studies.require(db, study_id)
    try:
        _validate_readings(data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    other = db.scalar(select(TrialOrder).where(
        TrialOrder.study_id == study_id, TrialOrder.source_key == data.source_key
    ))
    if other and other.id != row_id:
        raise HTTPException(409, '源记录编号重复')
    if row_id:
        row = db.get(TrialOrder, row_id)
        if not row or row.study_id != study_id:
            raise HTTPException(404, '订单不存在')
        action = 'trial_order.update'
    else:
        if len(list_orders(db, study_id)) >= 5000:
            raise HTTPException(422, '小型研究最多5000条订单')
        row = TrialOrder(study_id=study_id, source_key=data.source_key,
                         created_at=now(), updated_at=now())
        db.add(row)
        action = 'trial_order.create'
    row.source_key = data.source_key
    row.paper_type = data.paper_type
    row.shift = data.shift
    row.arrived_at = data.arrived_at
    row.readings_visible_at = data.readings_visible_at
    row.before = data.before
    row.after = data.after
    row.updated_at = now()
    log(db, user, action, f'{study_id}/{data.source_key}')
    db.commit()
    return _order_dict(row)


def delete_order(db, study_id, row_id, user):
    row = db.get(TrialOrder, row_id)
    if not row or row.study_id != study_id:
        raise HTTPException(404, '订单不存在')
    db.delete(row)
    log(db, user, 'trial_order.delete', f'{study_id}/{row.source_key}')
    db.commit()
    return {'deleted': True}


def list_quotas(db):
    return [{'shift': x.shift, 'quota': x.quota, 'updated_at': x.updated_at}
            for x in db.scalars(select(ShiftQuota).order_by(ShiftQuota.shift))]


def set_quota(db, shift, data, user):
    shift = shift.strip()
    if not shift:
        raise HTTPException(422, '班次不能为空')
    row = db.scalar(select(ShiftQuota).where(ShiftQuota.shift == shift))
    if row:
        row.quota = data.quota
        row.updated_at = now()
    else:
        row = ShiftQuota(shift=shift, quota=data.quota, updated_at=now())
        db.add(row)
    log(db, user, 'shift_quota.set', f'{shift}={data.quota}')
    db.commit()
    return {'shift': row.shift, 'quota': row.quota, 'updated_at': row.updated_at}


def _snapshot_session():
    """订单与班次名额必须在同一快照里读出；PostgreSQL 用 REPEATABLE READ。"""
    bind = engine
    if engine.dialect.name == 'postgresql':
        bind = engine.execution_options(isolation_level='REPEATABLE READ')
    return Session(bind=bind)


def _freeze(study_id, as_of):
    """在一个可重复读事务里一起读出订单与班次名额，作为同一冻结快照。

    冻结时刻之后才可见的读数不会进入快照，避免回放改用补录数据。
    """
    orders = []
    with _snapshot_session() as snap:
        # 时间在 Python 侧规范化后比较，避免不同存储格式的字符串序不一致。
        for x in snap.scalars(select(TrialOrder).where(TrialOrder.study_id == study_id)):
            item = _order_dict(x)
            if item['arrived_at'] > as_of:
                continue
            if item['readings_visible_at'] is None or item['readings_visible_at'] > as_of:
                item['before'] = None
                item['after'] = None
            orders.append(item)
        quotas = {x.shift: x.quota for x in snap.scalars(
            select(ShiftQuota).order_by(ShiftQuota.shift)
        )}
    # 规范排序后再入快照，保证相同冻结内容得到相同 SHA256。
    orders.sort(key=_order_key)
    return orders, quotas


def _replay_record(row, replay_existing=False):
    data = record(row)
    data['replay_existing'] = replay_existing
    return data


def create(db, data, user):
    existing = db.scalar(select(AllocationReplay).where(
        AllocationReplay.idempotency_key == data.idempotency_key
    ))
    if existing:
        same_request = (
            existing.study_id == data.study_id
            and existing.threshold == data.threshold
            and (data.as_of is None or existing.as_of == data.as_of)
        )
        if not same_request:
            raise HTTPException(409, '幂等键已用于不同的回放请求')
        return _replay_record(existing, replay_existing=True)

    studies.require(db, data.study_id)
    as_of = data.as_of or parse_timestamp(now(), '回放时刻')
    orders, quotas = _freeze(data.study_id, as_of)
    snapshot = {'as_of': as_of, 'threshold': data.threshold, 'orders': orders, 'quotas': quotas}
    result = simulate(orders, quotas, data.threshold, as_of)
    row = AllocationReplay(
        study_id=data.study_id, name=data.name, idempotency_key=data.idempotency_key,
        as_of=as_of, threshold=data.threshold, snapshot=snapshot,
        checksum=checksum(snapshot), result=result, created_at=now(),
        created_by=getattr(user, 'email', str(user)),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # 并发重试同一幂等键：不新增，返回已存在的那次冻结结果。
        db.rollback()
        existing = db.scalar(select(AllocationReplay).where(
            AllocationReplay.idempotency_key == data.idempotency_key
        ))
        if not existing:
            raise HTTPException(409, '回放请求冲突，请重试')
        if existing.study_id != data.study_id or existing.threshold != data.threshold:
            raise HTTPException(409, '幂等键已用于不同的回放请求')
        return _replay_record(existing, replay_existing=True)
    log(db, user, 'replay.create', f'{row.id} {data.name}')
    db.commit()
    return _replay_record(row)


def get(db, replay_id):
    row = db.get(AllocationReplay, replay_id)
    if not row:
        raise HTTPException(404, '回放不存在')
    return record(row)


def list_replays(db, study_id=None):
    stmt = select(AllocationReplay).order_by(AllocationReplay.id.desc())
    if study_id is not None:
        stmt = stmt.where(AllocationReplay.study_id == study_id)
    items = []
    for row in db.scalars(stmt):
        item = record(row)
        item.pop('snapshot', None)  # 列表视图不返回整份冻结快照
        items.append(item)
    return items


def export(db, replay_id, user):
    row = get(db, replay_id)
    result = row['result']
    comparison = result['comparison']
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['回放编号', row['id'], '名称', row['name'], '冻结时刻', row['as_of'],
                     '门槛', row['threshold'], '输入校验SHA256', row['checksum']])
    writer.writerow([])
    writer.writerow(['口径', '订单数', '平均色差 ΔE'])
    writer.writerow(['按此派单', comparison['orders_counted'],
                     '' if comparison['dispatch_mean_delta_e'] is None else comparison['dispatch_mean_delta_e']])
    writer.writerow(['全部走原工艺', comparison['orders_counted'],
                     '' if comparison['all_original_mean_delta_e'] is None else comparison['all_original_mean_delta_e']])
    writer.writerow(['差额(派单−全原工艺)',
                     '',
                     '' if comparison['difference'] is None else comparison['difference']])
    writer.writerow([])
    writer.writerow(['订单编号', '源记录', '纸类', '班次', '到单时刻', '读数可见时刻',
                     '原工艺ΔE', '新工艺ΔE', '派单依据单数', '依据平均改善', '本班余额',
                     '是否选新工艺', '是否计入对比', '派单使用色差', '说明'])
    for d in result['decisions']:
        writer.writerow([
            d['order_id'], d['source_key'], d['paper_type'], d['shift'], d['arrived_at'],
            d['readings_visible_at'] or '', d['before'] if d['before'] is not None else '',
            d['after'] if d['after'] is not None else '', d['basis_count'],
            '' if d['average_improvement'] is None else d['average_improvement'],
            d['quota_before'], '是' if d['selected'] else '否',
            '是' if d['counted'] else '否',
            '' if d['color_used'] is None else d['color_used'],
            d['reason'] + ('；' + d['note'] if d['note'] else ''),
        ])
    log(db, user, 'replay.export', replay_id)
    db.commit()
    return '﻿' + stream.getvalue()
