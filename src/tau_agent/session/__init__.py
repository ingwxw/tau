"""Append-only session persistence primitives."""

from tau_agent.session.entries import MessageEntry, SessionEntry
from tau_agent.session.jsonl import (
    SessionJsonlError,
    entry_from_json_line,
    entry_to_json_line,
)
from tau_agent.session.memory import SessionState, replay_messages
from tau_agent.session.storage import (
    InMemorySessionStorage,
    JsonlSessionStorage,
    SessionStorage,
)

__all__ = [
    "InMemorySessionStorage",
    "JsonlSessionStorage",
    "MessageEntry",
    "SessionEntry",
    "SessionJsonlError",
    "SessionState",
    "SessionStorage",
    "entry_from_json_line",
    "entry_to_json_line",
    "replay_messages",
]
