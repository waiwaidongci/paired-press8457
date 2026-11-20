import json
import numpy as np
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.domain import DOMAIN
from src.models.user import User
from src.models.study import Study
from src.models.observation import Observation
from src.models.replay import TrialOrder,ShiftQuota
from src.models import run,review,audit
from src.utils.security import hash_password
from src.utils.serializers import now

# 2026-11-19 的合成派单样本：含不同纸类、同刻抢最后一个名额、读数后到等情形。
TRIAL_SAMPLES=[
    ('TRIAL-0001','米白纸','白班','2026-11-19T09:00:00Z','2026-11-19T09:05:00Z',3.20,2.70),
    ('TRIAL-0002','米白纸','白班','2026-11-19T09:10:00Z','2026-11-19T09:14:00Z',2.90,2.10),
    ('TRIAL-0003','棉纸','白班','2026-11-19T09:15:00Z','2026-11-19T09:18:00Z',3.60,3.50),
    ('TRIAL-0006','米白纸','白班','2026-11-19T09:20:00Z','2026-11-20T08:00:00Z',3.00,1.90),
    ('TRIAL-0004','米白纸','白班','2026-11-19T09:30:00Z','2026-11-19T09:34:00Z',3.10,2.40),
    ('TRIAL-0005','米白纸','白班','2026-11-19T09:30:00Z','2026-11-19T09:36:00Z',2.80,2.30),
    ('TRIAL-0007','轻涂纸','白班','2026-11-19T09:45:00Z','2026-11-19T09:50:00Z',4.10,3.90),
    ('TRIAL-0008','米白纸','白班','2026-11-19T09:50:00Z','2026-11-19T09:55:00Z',3.30,2.80),
    ('TRIAL-0009','米白纸','夜班','2026-11-19T21:00:00Z','2026-11-19T21:08:00Z',3.50,3.00),
    ('TRIAL-0010','米白纸','夜班','2026-11-19T21:20:00Z','2026-11-19T21:25:00Z',2.70,2.10),
    ('TRIAL-0011','棉纸','夜班','2026-11-19T21:30:00Z','2026-11-19T21:35:00Z',3.80,3.70),
    ('TRIAL-0012','米白纸','夜班','2026-11-19T21:40:00Z',None,3.00,None),
]
SHIFT_QUOTAS={'白班':3,'夜班':1}


def _seed_dispatch(db,study):
    stamp=now()
    if not db.scalar(select(TrialOrder.id).where(TrialOrder.study_id==study.id)):
        for key,paper,shift,arrived,visible,before,after in TRIAL_SAMPLES:
            db.add(TrialOrder(study_id=study.id,source_key=key,paper_type=paper,shift=shift,
                              arrived_at=arrived,readings_visible_at=visible,
                              before=before,after=after,created_at=stamp,updated_at=stamp))
    for shift,quota in SHIFT_QUOTAS.items():
        if not db.scalar(select(ShiftQuota.id).where(ShiftQuota.shift==shift)):
            db.add(ShiftQuota(shift=shift,quota=quota,updated_at=stamp))

def seed():
    Base.metadata.create_all(engine)
    rng=np.random.default_rng(42)
    i=DOMAIN['index']
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Research2026!')))
        for k,name in enumerate(DOMAIN['names']):
            study=db.scalar(select(Study).where(Study.name==name))
            if not study:
                study=Study(name=name,source_filename=DOMAIN['slug']+f'-202611-{k+1}.csv',description='独立合成业务观测 / 固定种子42 / 仅用于方法与流程演示');db.add(study);db.flush()
            rows=[]
            if i==0:
                for n in range(120): rows.append({'moisture':round(float(np.clip(rng.normal(5.2+k*.7,.7),0,100)),3),'extract':round(float(np.clip(rng.normal(34+k*2,2.4),0,100)),3)})
            elif i==1:
                rows=[{'group':'A','success':87+k*2,'failure':13-k*2},{'group':'B','success':96-k,'failure':4+k}]
            elif i==2:
                for n in range(24):
                    b=float(rng.uniform(3,6));rows.append({'before':round(b,3),'after':round(max(.1,b+rng.normal(-.45+k*.3,.5)),3)})
            elif i==3:
                for n in range(90):
                    x=round(float(rng.uniform(4,28)),1);rows.append({'porosity':x,'absorption':round(max(0,x*(.18+k*.08)+rng.normal(0,1.5)),2)})
            else: rows=[{'p0':.08+k*.02,'p1':.1+k*.025,'cost_per_contact':.12+k*.04,'budget':3000+k*500}]
            for n,values in enumerate(rows):
                key=f'DEMO-{k+1}-{n+1:04}'
                if not db.scalar(select(Observation.id).where(Observation.study_id==study.id,Observation.source_key==key)):
                    db.add(Observation(study_id=study.id,source_key=key,values=values))
            if k==0: _seed_dispatch(db,study)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (User,Study,Observation,TrialOrder)}
        print(json.dumps(counts));return counts
if __name__=='__main__': seed()
