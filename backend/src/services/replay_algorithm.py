"""名额派单回放的纯计算。

输入必须是已经冻结的订单、班次名额和门槛；函数不读取数据库，也不依赖当前时间，
因此同一份快照总能得到同样的结果。

口径：
- 逐单按到单时刻排序，同刻按编号（自然序，如 QM-2 在 QM-10 之前；再同则按记录 id）。
- 依据只取“当时已齐”的较早同类订单：同类指同纸类、到单更早，且读数可见时刻不晚于本单到单时刻。
  同刻的两单互不作为依据。
- 平均改善 = 依据订单 (原工艺 ΔE − 新工艺 ΔE) 的均值；严格大于门槛才考虑新工艺。
- 未齐读数（缺任一侧或可见时刻未到）不计入两套平均，但已占用的名额照扣。

时间字段统一为规范化后的 UTC ISO 字符串（固定宽度），可按字典序比较。
"""
from statistics import mean
import re


def _natural_key(text):
    """把编号按“自然序”切分：数字段按数值比较，其余按文本比较。

    例如 QM-2 排在 QM-10 之前，避免纯字典序把 10 排在 2 前面。
    """
    parts = re.split(r'(\d+)', text or '')
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]


def _order_key(order):
    return (order['arrived_at'], _natural_key(order['source_key']), order['id'])


def _complete(order):
    return (
        order.get('before') is not None
        and order.get('after') is not None
        and order.get('readings_visible_at') is not None
    )


def _visible_by(order, at):
    return _complete(order) and order['readings_visible_at'] <= at


def _reason(selected, basis_count, average, threshold, quota_before):
    if basis_count == 0:
        return '无较早同类完整读数，按原工艺'
    if average is None or average <= threshold:
        return '同类平均改善未超过门槛，按原工艺'
    if quota_before <= 0:
        return '本班名额已用完，按原工艺'
    if selected:
        return '同类平均改善超过门槛且本班有名额，选新工艺'
    return '按原工艺'


def simulate(orders, quotas, threshold, as_of):
    ordered = sorted(orders, key=_order_key)
    remaining = {k: int(v) for k, v in (quotas or {}).items()}
    history = []
    decisions = []

    for order in ordered:
        arrived = order['arrived_at']
        evidence = [
            h for h in history
            if h['paper_type'] == order['paper_type']
            and h['arrived_at'] < arrived
            and _visible_by(h, arrived)
        ]
        basis_count = len(evidence)
        average = mean(h['before'] - h['after'] for h in evidence) if evidence else None
        quota_before = int(remaining.get(order['shift'], 0))
        selected = (
            basis_count > 0
            and average is not None
            and average > threshold
            and quota_before > 0
        )
        if selected:
            remaining[order['shift']] = quota_before - 1

        # 对比口径只看冻结时刻已可见的成对读数；未齐读数两边都不计。
        counted = _visible_by(order, as_of)
        quota_after = quota_before - (1 if selected else 0)
        decisions.append({
            'order_id': order['id'],
            'source_key': order['source_key'],
            'paper_type': order['paper_type'],
            'shift': order['shift'],
            'arrived_at': arrived,
            'readings_visible_at': order.get('readings_visible_at'),
            'before': order.get('before'),
            'after': order.get('after'),
            'selected': bool(selected),
            'basis_count': basis_count,
            'average_improvement': average,
            'threshold': threshold,
            'quota_before': quota_before,
            'quota_after': quota_after,
            'counted': bool(counted),
            'color_used': (order['after'] if selected else order['before']) if counted else None,
            'reason': _reason(selected, basis_count, average, threshold, quota_before),
            'note': '读数未齐，两套平均均不计，但已占本班名额' if selected and not counted else '',
        })

        # 自己的读数不参与自己的选择；只有已齐订单才能成为后续依据。
        if _complete(order):
            history.append(order)

    counted = [d for d in decisions if d['counted']]
    dispatch = [d['color_used'] for d in counted if d['color_used'] is not None]
    original = [d['before'] for d in counted if d['before'] is not None]
    dispatch_mean = mean(dispatch) if dispatch else None
    original_mean = mean(original) if original else None
    selected_orders = [d for d in decisions if d['selected']]

    shifts = []
    for shift in sorted({o['shift'] for o in ordered}):
        used = sum(1 for d in decisions if d['shift'] == shift and d['selected'])
        shifts.append({
            'shift': shift,
            'quota': int((quotas or {}).get(shift, 0)),
            'selected': used,
            'remaining': int(remaining.get(shift, 0)),
        })

    return {
        'threshold': threshold,
        'as_of': as_of,
        'decisions': decisions,
        'selected': selected_orders,
        'comparison': {
            'orders_total': len(decisions),
            'orders_counted': len(counted),
            'orders_excluded_incomplete': len(decisions) - len(counted),
            'selected_count': len(selected_orders),
            'dispatch_mean_delta_e': dispatch_mean,
            'all_original_mean_delta_e': original_mean,
            'difference': (
                dispatch_mean - original_mean
                if dispatch_mean is not None and original_mean is not None
                else None
            ),
        },
        'shifts': shifts,
    }
