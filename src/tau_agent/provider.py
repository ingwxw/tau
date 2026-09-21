from collections.abc import AsyncGenerator
from typing import Protocol
from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentTool

from tau_agent.messages import AssistantMessage, UserMessage
from tau_agent.provider_events import AssistantMessageEvent

class ModelProvider(Protocol):
    def stream_response(
            self,
            *,
            model: str,
            system: str,
            messages: list[AgentMessage],
            tools: list[AgentTool],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        ...
