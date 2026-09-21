from dataclasses import dataclass, field
from typing import Literal
from tau_agent.messages import AssistantMessage

@dataclass
class TextDeltaEvent:
    delta: str
    type: Literal["text_delta"] = field(default="text_delta", init=False)

@dataclass
class AssistantDoneEvent:
    message: AssistantMessage
    type: Literal["assistant_done"] = field(default="assistant_done", init=False)

@dataclass
class AssistantStartEvent:
    type: Literal["assistant_start"] = field(default="assistant_start", init=False)

type AssistantMessageEvent = (
    AssistantStartEvent | TextDeltaEvent | AssistantDoneEvent
)

