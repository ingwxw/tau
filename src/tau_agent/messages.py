from dataclasses import dataclass, field
from typing import Literal

@dataclass
class TextContent:
    text: str
    type: Literal["text"] = field(default="text", init=False)

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]
    type: Literal["tool_call"] = field(default="tool_call", init=False)

@dataclass
class UserMessage:
    content: str
    role: Literal["user"] = field(default="user", init=False)

@dataclass
class AssistantMessage:
    content: list[TextContent | ToolCall]
    role: Literal["assistant"] = field(default="assistant", init=False)
@dataclass
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    role: Literal["tool_result"] = field(default="tool_result", init=False)

type AgentMessage = UserMessage | AssistantMessage | ToolResultMessage


