import asyncio
from check_tools import EchoTool
from tau_agent.events import AgentEvent, ToolExecutionEndEvent,ToolExecutionStartEvent,AgentEndEvent
from tau_agent.harness import AgentHarness
from tau_ai.fake import FakeToolProvider
from tau_agent.messages import ToolResultMessage


async def main():
    # 初始化harness
    harness = AgentHarness(
        provider=FakeToolProvider(),
        model="fake",
        system="fake",
        max_turns=10,
        tools=[EchoTool()],
    )
    end_events: list[AgentEndEvent] = []
    observed: list[ToolExecutionEndEvent] = []
    # 定义监听器
    def listener(event: AgentEvent) -> None:
        if isinstance(event, ToolExecutionEndEvent):
            assert any(
                message is event.result
                for message in harness.messages
            )
            observed.append(event)
            print("工具执行结果已经在历史记录中了")
        if isinstance(event, AgentEndEvent):
            end_events.append(event)
    # 订阅监听器
    unsubscribe = harness.subscribe(listener)

    # 消费 harness.prompt(...)，收到 ToolExecutionStartEvent 就调用 harness.cancel()。
    # 用 except asyncio.CancelledError 捕获取消；如果正常结束，则通过 else 抛出 AssertionError。

    try:
        async for event in harness.prompt("测试cancellation"):
            if isinstance(event, ToolExecutionStartEvent):
                harness.cancel()
    except asyncio.CancelledError:
        print("已经取消循环")
    else:
        raise AssertionError("取消失败")
    assert len(observed) == 1
    messages = harness.messages
    assert harness.is_running is False
    assert [message.role for message in harness.messages] == [
        "user", "assistant", "tool_result"
    ]
    result = harness.messages[-1]
    assert isinstance(result, ToolResultMessage)
    assert result.is_error is True
    assert result.tool_call_id == "call_1"
    print("取消检查成功")
    assert len(end_events) == 1
    assert end_events[0].reason == "cancelled"
    assert end_events[0].error_message is None
    print("代理结束检查成功")





if __name__ == "__main__":
    asyncio.run(main())