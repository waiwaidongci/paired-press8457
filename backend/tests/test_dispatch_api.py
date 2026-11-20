from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.config.database import Base, engine, Session
from src.models import user, study, observation, run, review, audit, replay  # noqa: F401
from src.models.study import Study
from src.models.user import User
from src.models.replay import AllocationReplay
from src.routes import replays as replay_routes
from src.utils.security import hash_password, token


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ('admin', 'viewer'):
            db.add(User(email=role + '@demo.local', role=role,
                        password_hash=hash_password('Research2026!')))
        db.add(Study(name='接口测试批次', source_filename='api.csv', description=''))
        db.commit()
        study_id = db.scalar(select(Study.id))
        tokens = {role: token(db.scalar(select(User).where(User.email == role + '@demo.local')))
                  for role in ('admin', 'viewer')}
    app = FastAPI()
    app.include_router(replay_routes.router)
    app.state.study_id = study_id
    app.state.tokens = tokens
    return TestClient(app, raise_server_exceptions=False)


def auth(client, role='admin'):
    return {'Authorization': 'Bearer ' + client.app.state.tokens[role]}


def test_end_to_end_replay_through_http(client):
    sid = client.app.state.study_id
    headers = auth(client)

    q = client.put('/shift-quotas/白班', json={'quota': 1}, headers=headers)
    assert q.status_code == 200 and q.json()['quota'] == 1

    orders = [
        dict(source_key='A-001', paper_type='米白纸', shift='白班',
             arrived_at='2026-11-19T09:00:00Z', readings_visible_at='2026-11-19T09:02:00Z',
             before=3.0, after=2.0),
        # 读数后到：到单 09:10，10:00 才可见
        dict(source_key='A-002', paper_type='米白纸', shift='白班',
             arrived_at='2026-11-19T09:10:00Z', readings_visible_at='2026-11-19T10:00:00Z',
             before=3.0, after=1.0),
        # 同刻抢最后一个名额
        dict(source_key='A-003', paper_type='米白纸', shift='白班',
             arrived_at='2026-11-19T09:20:00Z', readings_visible_at='2026-11-19T09:21:00Z',
             before=3.0, after=2.0),
        dict(source_key='A-004', paper_type='米白纸', shift='白班',
             arrived_at='2026-11-19T09:20:00Z', readings_visible_at='2026-11-19T09:21:00Z',
             before=3.0, after=2.0),
        # 允许读数未齐：只有一侧；到单晚于冻结时刻，不进入本次回放
        dict(source_key='A-005', paper_type='米白纸', shift='白班',
             arrived_at='2026-11-19T09:40:00Z', readings_visible_at=None,
             before=3.2, after=None),
    ]
    for body in orders:
        r = client.post(f'/studies/{sid}/trial-orders', json=body, headers=headers)
        assert r.status_code == 200, r.text

    body = dict(study_id=sid, name='接口回放', as_of='2026-11-19T09:30:00Z',
                threshold=0.4, idempotency_key='http-key-1')
    first = client.post('/replays', json=body, headers=headers)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload['replay_existing'] is False
    keys = [d['source_key'] for d in payload['result']['decisions']]
    assert keys == ['A-001', 'A-002', 'A-003', 'A-004']  # A-005 到单晚于冻结时刻
    assert [d['source_key'] for d in payload['result']['selected']] == ['A-002']
    assert payload['result']['comparison']['orders_excluded_incomplete'] == 1

    retry = client.post('/replays', json=body, headers=headers)
    assert retry.status_code == 200
    assert retry.json()['id'] == payload['id']
    assert retry.json()['replay_existing'] is True
    with Session() as db:
        assert len(list(db.scalars(select(AllocationReplay)))) == 1

    csv = client.get(f"/replays/{payload['id']}/export", headers=headers)
    assert csv.status_code == 200
    assert 'text/csv' in csv.headers['content-type']
    assert '按此派单' in csv.text and '全部走原工艺' in csv.text

    listing = client.get(f'/replays?study_id={sid}', headers=headers)
    assert listing.status_code == 200
    assert 'snapshot' not in listing.json()[0]


def test_viewer_cannot_write_and_anonymous_is_rejected(client):
    sid = client.app.state.study_id
    viewer = auth(client, 'viewer')
    r = client.put('/shift-quotas/白班', json={'quota': 1}, headers=viewer)
    assert r.status_code == 403
    r = client.post(f'/studies/{sid}/trial-orders',
                    json=dict(source_key='V-1', paper_type='米白纸', shift='白班',
                              arrived_at='2026-11-19T09:00:00Z'),
                    headers=viewer)
    assert r.status_code == 403
    assert client.get('/shift-quotas').status_code == 401


def test_invalid_backfill_is_rejected(client):
    sid = client.app.state.study_id
    headers = auth(client)
    # 成对读数已齐却没有可见时刻
    r = client.post(f'/studies/{sid}/trial-orders',
                    json=dict(source_key='X-1', paper_type='米白纸', shift='白班',
                              arrived_at='2026-11-19T09:00:00Z',
                              before=3.0, after=2.0), headers=headers)
    assert r.status_code == 422
    # 读数可见早于到单
    r = client.post(f'/studies/{sid}/trial-orders',
                    json=dict(source_key='X-2', paper_type='米白纸', shift='白班',
                              arrived_at='2026-11-19T09:00:00Z',
                              readings_visible_at='2026-11-19T08:00:00Z',
                              before=3.0, after=2.0), headers=headers)
    assert r.status_code == 422
    # 负数色差
    r = client.post(f'/studies/{sid}/trial-orders',
                    json=dict(source_key='X-3', paper_type='米白纸', shift='白班',
                              arrived_at='2026-11-19T09:00:00Z',
                              before=-1, after=2.0), headers=headers)
    assert r.status_code == 422
