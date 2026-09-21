"""Append-only session storage implementations."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from tau_agent.session.entries import SessionEntry
from tau_agent.session.jsonl import entries_from_json_lines, entry_to_json_line


class SessionStorage(Protocol):
    def append(self, entry: SessionEntry) -> None:
        ...

    def read_all(self) -> list[SessionEntry]:
        ...


class InMemorySessionStorage:
    def __init__(self, entries: Sequence[SessionEntry] = ()) -> None:
        self.entries = list(entries)

    def append(self, entry: SessionEntry) -> None:
        self.entries.append(entry)

    def read_all(self) -> list[SessionEntry]:
        return list(self.entries)


class JsonlSessionStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: SessionEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(entry_to_json_line(entry))
            file.flush()
            os.fsync(file.fileno())

    def read_all(self) -> list[SessionEntry]:
        if not self.path.exists():
            return []
        return entries_from_json_lines(
            self.path.read_text(encoding="utf-8").splitlines()
        )
