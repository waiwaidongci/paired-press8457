from fastapi import APIRouter,Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.middlewares.auth import current_user,writer
from src.schemas.replay import TrialOrderInput,ShiftQuotaInput,ReplayInput
from src.services import replays
router=APIRouter()


@router.get('/studies/{study_id}/trial-orders')
def list_orders(study_id:int,db=Depends(get_db),user=Depends(current_user)):
    return replays.list_orders(db,study_id)


@router.post('/studies/{study_id}/trial-orders')
def add_order(study_id:int,data:TrialOrderInput,db=Depends(get_db),user=Depends(writer)):
    return replays.save_order(db,study_id,data,user)


@router.put('/studies/{study_id}/trial-orders/{row_id}')
def update_order(study_id:int,row_id:int,data:TrialOrderInput,db=Depends(get_db),user=Depends(writer)):
    return replays.save_order(db,study_id,data,user,row_id)


@router.delete('/studies/{study_id}/trial-orders/{row_id}')
def remove_order(study_id:int,row_id:int,db=Depends(get_db),user=Depends(writer)):
    return replays.delete_order(db,study_id,row_id,user)


@router.get('/shift-quotas')
def list_quotas(db=Depends(get_db),user=Depends(current_user)):
    return replays.list_quotas(db)


@router.put('/shift-quotas/{shift}')
def set_quota(shift:str,data:ShiftQuotaInput,db=Depends(get_db),user=Depends(writer)):
    return replays.set_quota(db,shift,data,user)


@router.get('/replays')
def list_replays(study_id:int|None=None,db=Depends(get_db),user=Depends(current_user)):
    return replays.list_replays(db,study_id)


@router.post('/replays')
def create_replay(data:ReplayInput,db=Depends(get_db),user=Depends(writer)):
    return replays.create(db,data,user)


@router.get('/replays/{replay_id}')
def get_replay(replay_id:int,db=Depends(get_db),user=Depends(current_user)):
    return replays.get(db,replay_id)


@router.get('/replays/{replay_id}/export')
def export_replay(replay_id:int,db=Depends(get_db),user=Depends(current_user)):
    content=replays.export(db,replay_id,user).encode('utf-8')
    return Response(content=content,media_type='text/csv',
                    headers={'Content-Disposition':f'attachment; filename="dispatch-replay-{replay_id}.csv"'})
