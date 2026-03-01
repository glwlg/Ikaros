from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth.users import current_active_user
from api.auth.models import User
from core import state_store

router = APIRouter()


class TaskCreate(BaseModel):
    crontab: str
    instruction: str


class TaskStatusUpdate(BaseModel):
    is_active: bool


@router.get("/")
def get_tasks(current_user: User = Depends(current_active_user)):
    return state_store.get_all_active_tasks(current_user.id)


@router.post("/")
def create_task(task: TaskCreate, current_user: User = Depends(current_active_user)):
    try:
        state_store.add_scheduled_task(task.crontab, task.instruction, current_user.id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}")
def delete_task(task_id: int, current_user: User = Depends(current_active_user)):
    try:
        state_store.delete_task(task_id, current_user.id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{task_id}/status")
def update_task_status(
    task_id: int,
    status: TaskStatusUpdate,
    current_user: User = Depends(current_active_user),
):
    try:
        state_store.update_task_status(task_id, status.is_active, current_user.id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
