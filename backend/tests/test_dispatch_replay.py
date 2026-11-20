from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.config.database import Base, engine, Session
from src.models import user, study, observation, run, review, audit, replay  # noqa: F401
from src.models.study import Study
from src.models.replay import TrialOrder, ShiftQuota, AllocationReplay
from src.services import replays
from src.schemas.replay import TrialOrderInput, ShiftQuotaInput, ReplayInput
from fastapi import HTTPException


USER = SimpleNamespace(email='analyst@demo.local', role='analyst')


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def make_study(name='派单测试批次'):
    with Session() as db:
        s = Study(name=name, source_filename='dispatch.csv', description='test')
        db.add(s)
        db.commit()
        return s.id


def add_order(study_id, key, paper='米白纸', shift='白班', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:00:00Z', before=3.0, after=2.0):
    with Session() as db:
        data = TrialOrderInput(source_key=key, paper_type=paper, shift=shift,
                               arrived_at=arrived, readings_visible_at=visible,
                               before=before, after=after)
        return replays.save_order(db, study_id, data, USER)


def set_quota(shift, quota):
    with Session() as db:
        replays.set_quota(db, shift, ShiftQuotaInput(quota=quota), USER)


def run_replay(study_id, as_of, threshold=0.4, key=None):
    with Session() as db:
        data = ReplayInput(study_id=study_id, name='回放', as_of=as_of,
                           threshold=threshold, idempotency_key=key or 'k-' + as_of)
        return replays.create(db, data, USER)


def decision(result, key):
    return next(d for d in result['result']['decisions'] if d['source_key'] == key)


def test_basis_uses_only_earlier_complete_same_paper():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'S-001', paper='米白纸', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:05:00Z', before=3.0, after=2.0)  # 改善 1.0
    add_order(sid, 'S-002', paper='棉纸', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=3.0, after=2.9)  # 不同纸类，无依据
    add_order(sid, 'S-003', paper='米白纸', arrived='2026-11-19T09:20:00Z',
              visible='2026-11-19T09:20:00Z', before=3.0, after=2.4)  # 有依据，改善 1.0

    out = run_replay(sid, '2026-11-19T10:00:00Z')
    assert decision(out, 'S-001')['selected'] is False
    assert decision(out, 'S-001')['basis_count'] == 0
    assert decision(out, 'S-002')['selected'] is False
    assert decision(out, 'S-002')['basis_count'] == 0  # 棉纸没有同类依据
    assert decision(out, 'S-003')['basis_count'] == 1  # 只用同纸类已齐订单
    assert decision(out, 'S-003')['selected'] is True
    assert out['result']['shifts'][0]['remaining'] == 0


def test_same_instant_competes_for_last_slot_by_source_key():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'S-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:00:00Z', before=3.0, after=2.0)
    add_order(sid, 'S-002', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=3.0, after=2.0)
    add_order(sid, 'S-010', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=3.0, after=2.0)

    out = run_replay(sid, '2026-11-19T10:00:00Z')
    order = [d['source_key'] for d in out['result']['decisions']]
    assert order == ['S-001', 'S-002', 'S-010']
    assert decision(out, 'S-002')['selected'] is True
    assert decision(out, 'S-002')['basis_count'] == 1
    assert decision(out, 'S-010')['selected'] is False
    # 同为 09:10 的两单互不作为依据：S-010 只看到更早的 S-001
    assert decision(out, 'S-010')['basis_count'] == 1
    assert decision(out, 'S-010')['reason'].startswith('本班名额已用完')
    # 只有 1 个名额，同刻两单只有编号较小者拿到
    assert out['result']['comparison']['selected_count'] == 1


def test_same_instant_natural_order_puts_2_before_10():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'QM-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:00:00Z', before=3.0, after=2.0)
    add_order(sid, 'QM-10', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=3.0, after=2.0)
    add_order(sid, 'QM-2', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=3.0, after=2.0)

    out = run_replay(sid, '2026-11-19T10:00:00Z')
    order = [d['source_key'] for d in out['result']['decisions']]
    assert order == ['QM-001', 'QM-2', 'QM-10']
    assert decision(out, 'QM-2')['selected'] is True
    assert decision(out, 'QM-10')['selected'] is False


def test_unread_order_selected_still_consumes_quota_and_is_excluded_from_means():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'S-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:05:00Z', before=3.0, after=2.0)
    # 到单 09:10，读数 10:00 才可见：冻结时刻 09:30 尚未齐
    add_order(sid, 'S-002', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T10:00:00Z', before=3.0, after=1.0)
    add_order(sid, 'S-003', arrived='2026-11-19T09:20:00Z',
              visible='2026-11-19T09:25:00Z', before=3.0, after=2.0)

    out = run_replay(sid, '2026-11-19T09:30:00Z')
    s2 = decision(out, 'S-002')
    assert s2['selected'] is True          # 依据 S-001 改善 1.0 超过门槛
    assert s2['counted'] is False          # 读数未齐
    assert s2['quota_before'] == 1 and s2['quota_after'] == 0
    assert '已占本班名额' in s2['note']
    # 名额被扣掉，S-003 即使有依据也走原工艺
    assert decision(out, 'S-003')['quota_before'] == 0
    assert decision(out, 'S-003')['selected'] is False
    comp = out['result']['comparison']
    assert comp['orders_counted'] == 2
    assert comp['orders_excluded_incomplete'] == 1
    # 未齐 S-002 两边都不计：派单均值 = A、C 的原工艺 3.0
    assert comp['dispatch_mean_delta_e'] == pytest.approx(3.0)
    assert comp['all_original_mean_delta_e'] == pytest.approx(3.0)
    assert comp['difference'] == pytest.approx(0.0)


def test_threshold_is_strict_and_no_basis_falls_back():
    sid = make_study()
    set_quota('白班', 2)
    add_order(sid, 'S-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:00:00Z', before=2.0, after=1.5)  # 改善 0.5
    add_order(sid, 'S-002', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T09:10:00Z', before=2.0, after=1.5)
    out = run_replay(sid, '2026-11-19T10:00:00Z', threshold=0.5)
    assert decision(out, 'S-001')['reason'].startswith('无较早同类完整读数')
    assert decision(out, 'S-002')['average_improvement'] == pytest.approx(0.5)
    assert decision(out, 'S-002')['selected'] is False  # 等于门槛不算超过
    assert decision(out, 'S-002')['reason'].startswith('同类平均改善未超过门槛')


def test_idempotent_retry_does_not_add_or_use_later_data():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'S-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T09:05:00Z', before=3.0, after=2.0)
    add_order(sid, 'S-002', arrived='2026-11-19T09:10:00Z',
              visible='2026-11-19T10:00:00Z', before=3.0, after=1.0)

    first = run_replay(sid, '2026-11-19T09:30:00Z', key='replay-key-1')
    assert first['replay_existing'] is False
    original_result = first['result']
    original_checksum = first['checksum']

    # 冻结之后补录更早的可见时刻：回放重试不得改用补录数据
    with Session() as db:
        row = db.scalar(select(TrialOrder).where(TrialOrder.source_key == 'S-002'))
        row.readings_visible_at = '2026-11-19T09:08:00.000000+00:00'
        db.commit()

    second = run_replay(sid, '2026-11-19T09:30:00Z', key='replay-key-1')
    assert second['id'] == first['id']
    assert second['replay_existing'] is True
    assert second['checksum'] == original_checksum
    assert second['result'] == original_result

    with Session() as db:
        assert len(list(db.scalars(select(AllocationReplay)))) == 1

    # 相同幂等键但门槛不同：拒绝复用
    with Session() as db:
        data = ReplayInput(study_id=sid, name='回放', as_of='2026-11-19T09:30:00Z',
                           threshold=0.9, idempotency_key='replay-key-1')
        with pytest.raises(HTTPException) as err:
            replays.create(db, data, USER)
        assert err.value.status_code == 409


def test_snapshot_hides_readings_not_yet_visible_at_freeze():
    sid = make_study()
    set_quota('白班', 1)
    add_order(sid, 'S-001', arrived='2026-11-19T09:00:00Z',
              visible='2026-11-19T10:00:00Z', before=3.0, after=1.0)
    out = run_replay(sid, '2026-11-19T09:30:00Z')
    frozen = out['snapshot']['orders'][0]
    assert frozen['readings_visible_at'] == '2026-11-19T10:00:00.000000+00:00'
    assert frozen['before'] is None and frozen['after'] is None
