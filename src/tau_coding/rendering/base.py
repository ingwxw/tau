from typing import Protocol

from tau_agent.events import AgentEvent


class EventRenderer(Protocol):
    def render(self, event: AgentEvent) -> None:
        ...