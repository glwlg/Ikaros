from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth.router import get_current_user
from api.auth.models import User
from core import state_store

router = APIRouter()


class SubCreate(BaseModel):
    title: str
    feed_url: str


@router.get("/")
def get_rss(current_user: User = Depends(get_current_user)):
    return state_store.get_user_subscriptions(current_user.id)


@router.post("/")
def create_rss(sub: SubCreate, current_user: User = Depends(get_current_user)):
    # Since add_subscription runs synchronously and modifies DB via state_store
    try:
        state_store.add_subscription(current_user.id, sub.feed_url, sub.title)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{sub_id}")
def delete_rss(sub_id: int, current_user: User = Depends(get_current_user)):
    try:
        state_store.delete_subscription_by_id(sub_id, current_user.id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
