from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass(frozen=True)
class KernelSessionRef:
    provider: str
    session_id: str
    external_thread_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelTurnInput:
    text: str
    files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class KernelProvider(Protocol):
    provider: str

    async def ensure_session(self, session: dict[str, Any]) -> KernelSessionRef:
        ...

    async def start_turn(
        self,
        session: dict[str, Any],
        turn: dict[str, Any],
        input: KernelTurnInput,
    ) -> AsyncIterator[dict[str, Any]]:
        ...

    async def interrupt(self, turn_id: str) -> None:
        ...
