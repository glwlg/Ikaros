from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth.router import get_current_user
from api.auth.models import User
from core.heartbeat_store import HeartbeatStore

router = APIRouter()
hstore = HeartbeatStore()


class MonitorCreate(BaseModel):
    item: str


@router.get("/")
def get_monitors(current_user: User = Depends(get_current_user)):
    return hstore.list_checklist(str(current_user.id))


@router.post("/")
def create_monitor(
    monitor: MonitorCreate, current_user: User = Depends(get_current_user)
):
    try:
        hstore.add_checklist_item(str(current_user.id), monitor.item)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{index}")
def delete_monitor(index: int, current_user: User = Depends(get_current_user)):
    try:
        hstore.remove_checklist_item(str(current_user.id), index)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
