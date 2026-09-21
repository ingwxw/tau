import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import AsyncGenerator

from tau_agent.events import AgentEndEvent, ToolExecutionEndEvent
from tau_agent.messages import AssistantMessage, AgentMessage, ToolResultMessage, TextContent, ToolCall
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_agent.tools import AgentTool
from tau_coding.session import create_coding_session
class FakeReadProvider:
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
            assert result.tool_call_id == "read_1"
            assert result.content == "项目文件内容"
            assert result.is_error is False

            yield TextDeltaEvent(delta=text)
            yield AssistantDoneEvent(
                message=AssistantMessage(
                    content=[TextContent(text=text)]
                )
            )
            return
        call = ToolCall(
            id = "read_1",
            name = "read",
            arguments={
                "path": "sample.txt"
            },
        )

        # 其 content 中包含刚创建的 ToolCall
        yield AssistantDoneEvent(AssistantMessage([call]))






async def main():
    with TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        (project_dir / "sample.txt").write_text(
            "项目文件内容", encoding="utf-8"
        )
        session = create_coding_session(
            project_dir=project_dir,
            provider=FakeReadProvider(),
            model="fake model",
            system="fake system",
        )
        agent_end_events: list[AgentEndEvent] = []
        tool_end_events: list[ToolExecutionEndEvent] = []
        async for event in session.prompt("读取 sample.txt"):
            if isinstance(event, AgentEndEvent):
                agent_end_events.append(event)
            if isinstance(event, ToolExecutionEndEvent):
                tool_end_events.append(event)
        assert len(agent_end_events) == 1
        assert agent_end_events[0].reason == "completed"
        assert len(tool_end_events) == 1
        assert tool_end_events[0].result.content == "项目文件内容"
        print("CodingSession 文件读取链路检查通过")


if __name__ == "__main__":
    asyncio.run(main())
