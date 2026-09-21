import asyncio

from check_tools import EchoTool
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AgentMessage, ToolResultMessage, UserMessage
from tau_ai.fake import FakeToolProvider
from tau_agent.events import AgentEndEvent

async def check_turn_limit() -> None:
    end_events: list[AgentEndEvent] = []
    messages: list[AgentMessage] = []
    try:
        async for event in run_agent_loop(
                provider=FakeToolProvider(),
                model="fake",
                system="你是一个助手",
                messages=messages,
                tools=[EchoTool()],
                prompt=UserMessage(content="请用 echo 返回你好"),
                max_turns=1,
        ):
            if isinstance(event, AgentEndEvent):
                end_events.append(event)
    except RuntimeError as exc:
        assert str(exc) == "已达到最大轮数：1"
    else:
        raise AssertionError("应该触发轮数限制")
    roles = [message.role for message in messages]
    assert roles == ["user", "assistant", "tool_result"]
    assert len(end_events) == 1
    assert end_events[0].reason == "error"
    assert end_events[0].error_message == "已达到最大轮数：1"
    print("轮数限制检查通过")


async def main() -> None:
    messages: list[AgentMessage] = []

    async for event in run_agent_loop(
        provider=FakeToolProvider(),
        model="fake",
        system="你是一个助手",
        messages=messages,
        tools=[EchoTool()],
        prompt=UserMessage(content="请用 echo 返回你好"),
    ):
        print(event.type)
        if isinstance(event, AgentEndEvent):
            assert event.reason == "completed"
            assert event.error_message is None

    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool_result",
        "assistant",
    ]

    result = messages[2]
    assert isinstance(result, ToolResultMessage)
    assert result.tool_call_id == "call_1"
    assert result.content == "你好"
    assert result.is_error is False


    print("工具循环检查通过")
    await check_turn_limit()

if __name__ == "__main__":
    asyncio.run(main())
