from dataclasses import dataclass, field
from typing import Literal
from tau_agent.provider_events import AssistantMessageEvent
from tau_agent.messages import ToolCall, ToolResultMessage

@dataclass
class AgentStartEvent:
    type: Literal["agent_start"] = field(default="agent_start", init=False)

@dataclass
class AgentEndEvent:
    reason: Literal["completed", "cancelled", "error"]
    error_message: str | None = None
    type: Literal["agent_end"] = field(default="agent_end", init=False)

@dataclass
class MessageUpdateEvent:
    assistant_message_event: AssistantMessageEvent
    type: Literal["message_update"] = field(default="message_update", init=False)

@dataclass
class ToolExecutionStartEvent:
    call: ToolCall
    type: Literal["tool_execution_start"] = field(default="tool_execution_start", init=False)

@dataclass
class ToolExecutionEndEvent:
    result: ToolResultMessage
    type: Literal["tool_execution_end"] = field(default="tool_execution_end", init=False)



type AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | MessageUpdateEvent
    | ToolExecutionStartEvent
    | ToolExecutionEndEvent
)
