from __future__ import annotations

from pydantic import BaseModel, Field


class ChannelAccessUpdateRequest(BaseModel):
    access: dict[str, bool] = Field(default_factory=dict)


class ChannelRemarkUpdateRequest(BaseModel):
    remark: str = Field(default="", max_length=64)


class ToolPolicyUpdateRequest(BaseModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
