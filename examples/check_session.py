import asyncio
from pathlib import Path

from check_tools import EchoTool

from tau_agent.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from tau_agent.harness import AgentHarness
from tau_ai.fake import FakeToolProvider
from tau_coding.session import CodingSession


def build_session() -> tuple[CodingSession, AgentHarness]:
    harness = AgentHarness(
        provider=FakeToolProvider(),
        model="fake_model",
        system="fake_system",
        tools=[EchoTool()],
        max_turns=10,
    )
    session = CodingSession(
        project_dir=Path(__file__).parents[1],
        harness=harness,
    )
    return session, harness

async def main() -> None:
    session, harness = build_session()
    assert session.project_dir == Path(__file__).parents[1].resolve()
    print("Session 目录检查通过")

    # session.prompt 应该原样透传 harness 的事件
    events: list[AgentEvent] = []
    async for event in session.prompt("session测试"):
        events.append(event)

    assert isinstance(events[0], AgentStartEvent)
    assert isinstance(events[-1], AgentEndEvent)
    assert events[-1].reason == "completed"
    print("Session 事件透传检查通过")

    starts = [event for event in events if isinstance(event, ToolExecutionStartEvent)]
    ends = [event for event in events if isinstance(event, ToolExecutionEndEvent)]
    assert len(starts) == 1, "没有透传出工具调用事件"
    assert starts[0].call.name == "echo"
    assert len(ends) == 1
    assert ends[0].result.content == "你好"
    assert ends[0].result.is_error is False
    print("Session 工具事件检查通过")

    assert harness.is_running is False
    assert [message.role for message in harness.messages] == [
        "user", "assistant", "tool_result", "assistant"
    ]
    print("Session 历史检查通过")

    # session.cancel 应该能取消正在进行的 prompt
    session, harness = build_session()
    try:
        async for event in session.prompt("测试cancellation"):
            if isinstance(event, ToolExecutionStartEvent):
                session.cancel()
    except asyncio.CancelledError:
        print("已经取消循环")
    else:
        raise AssertionError("取消失败")

    assert harness.is_running is False
    print("Session 取消检查通过")
    agent_ends = [
        event for event in events
        if isinstance(event, AgentEndEvent)
    ]
    assert len(agent_ends) == 1
    assert agent_ends[0].reason == "completed"

if __name__ == "__main__":
    asyncio.run(main())
