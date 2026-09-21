from collections.abc import AsyncIterator
from tau_agent.messages import AgentMessage
from tau_agent.messages import AssistantMessage, TextContent, UserMessage
from tau_agent.messages import ToolCall, ToolResultMessage
from tau_agent.tools import AgentTool
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from collections.abc import AsyncGenerator


class FakeProvider:
    async def stream_response(
            self,
            *,
            model: str,
            system: str,
            messages: list[AgentMessage],
            tools: list[AgentTool],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        yield AssistantStartEvent()
        yield TextDeltaEvent("你")
        yield TextDeltaEvent("好")
        yield AssistantDoneEvent(AssistantMessage([TextContent("你好")]))

class FakeToolProvider:
    async def stream_response(
            self,
            *,
            model: str,
            system: str,
            messages: list[AgentMessage],
            tools: list[AgentTool],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        yield AssistantStartEvent()
        if messages and isinstance(messages[-1], ToolResultMessage):
            result = messages[-1]
            text = f"工具返回：{result.content}"

            yield TextDeltaEvent(delta=text)
            yield AssistantDoneEvent(
                message=AssistantMessage(
                    content=[TextContent(text=text)]
                )
            )
            return
        # TODO 1：创建 ToolCall
        # id="call_1"，name="echo"，arguments={"text": "你好"}
        call = ToolCall(
            id = "call_1",
            name = "echo",
            arguments = {
                "text": "你好"
            }
        )

        # TODO 2：通过 AssistantDoneEvent 返回一条 AssistantMessage
        # 其 content 中包含刚创建的 ToolCall
        yield AssistantDoneEvent(AssistantMessage([call]))
