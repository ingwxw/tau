"""Session entry models used by the append-only transcript."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Literal
from uuid import uuid4

from tau_agent.messages import AgentMessage


def new_entry_id() -> str:
    return uuid4().hex


@dataclass(frozen=True)
class MessageEntry:
    """One message in the session tree."""

    message: AgentMessage
    id: str = field(default_factory=new_entry_id)
    parent_id: str | None = None
    timestamp: float = field(default_factory=time)
    type: Literal["message"] = field(default="message", init=False)


type SessionEntry = MessageEntry
