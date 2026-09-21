"""Reconstruct runtime messages from the active session-tree path."""

from __future__ import annotations

from dataclasses import dataclass

from tau_agent.messages import AgentMessage
from tau_agent.session.entries import SessionEntry


class SessionTreeError(ValueError):
    pass


def entries_by_id(entries: list[SessionEntry]) -> dict[str, SessionEntry]:
    result: dict[str, SessionEntry] = {}
    for entry in entries:
        if entry.id in result:
            raise SessionTreeError(f"重复的 session entry id：{entry.id}")
        result[entry.id] = entry
    return result


def path_to_entry(
    entries: list[SessionEntry],
    leaf_id: str,
) -> list[SessionEntry]:
    by_id = entries_by_id(entries)
    path: list[SessionEntry] = []
    seen: set[str] = set()
    current_id: str | None = leaf_id

    while current_id is not None:
        if current_id in seen:
            raise SessionTreeError(f"session tree 存在环：{current_id}")
        seen.add(current_id)
        entry = by_id.get(current_id)
        if entry is None:
            raise SessionTreeError(f"找不到 parent entry：{current_id}")
        path.append(entry)
        current_id = entry.parent_id

    path.reverse()
    return path


def active_leaf_id(entries: list[SessionEntry]) -> str | None:
    return entries[-1].id if entries else None


def replay_messages(
    entries: list[SessionEntry],
    *,
    leaf_id: str | None = None,
) -> list[AgentMessage]:
    resolved_leaf_id = leaf_id or active_leaf_id(entries)
    if resolved_leaf_id is None:
        return []
    return [entry.message for entry in path_to_entry(entries, resolved_leaf_id)]


@dataclass(frozen=True)
class SessionState:
    entries: tuple[SessionEntry, ...]
    messages: tuple[AgentMessage, ...]
    active_leaf_id: str | None

    @classmethod
    def from_entries(
        cls,
        entries: list[SessionEntry],
        *,
        leaf_id: str | None = None,
    ) -> SessionState:
        resolved_leaf_id = leaf_id or active_leaf_id(entries)
        return cls(
            entries=tuple(entries),
            messages=tuple(replay_messages(entries, leaf_id=resolved_leaf_id)),
            active_leaf_id=resolved_leaf_id,
        )
