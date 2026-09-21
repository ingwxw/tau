import asyncio

from tau_agent.events import AgentEvent
from tau_ai.fake import FakeProvider
from tau_agent.harness import AgentHarness
async def main():
    consumed: list[AgentEvent] = []
    observed: list[AgentEvent] = []

    def listener(event: AgentEvent) -> None:
        observed.append(event)
    harness = AgentHarness(
        provider=FakeProvider(),
        model="fake",
        system="你是一个助手",
        tools=[],
        max_turns=10,
    )
    async for event in harness.prompt("我是小王"):
        pass
    async for event in harness.prompt("我叫什么"):
        pass
    history = harness.messages
    roles = [message.role for message in history]
    assert roles == ["user",
    "assistant",
    "user",
    "assistant",]
    print("Harness 历史检查通过")
    assert harness.is_running is False

    stream = harness.prompt("测试运行状态")
    assert harness.is_running is False

    try:
        first_event = await anext(stream)
        assert first_event.type == "agent_start"
        assert harness.is_running is True
    finally:
        await stream.aclose()

    assert harness.is_running is False
    print("Harness 状态检查通过")

    unsubscribe = harness.subscribe(listener)
    async for event in harness.prompt("测试订阅"):
        consumed.append(event)
    assert len(observed) > 0
    assert observed == consumed
    print("Harness 订阅检查通过")
    unsubscribe()
    unsubscribe()
    ori_len = len(observed)
    async for event in harness.prompt("测试订阅"):
        pass
    assert len(observed) == ori_len, "取消订阅后仍收到了事件"
    print("Harness 取消订阅检查通过")


    async_observed: list[AgentEvent] = []

    async def async_listener(event: AgentEvent) -> None:
        await asyncio.sleep(0)
        async_observed.append(event)

    unsubscribe_async = harness.subscribe(async_listener)

    count = 0
    async for event in harness.prompt("测试异步订阅"):
        count += 1
        assert len(async_observed) == count
        assert async_observed[-1] is event

    assert count > 0
    unsubscribe_async()
    print("Harness 异步订阅检查通过")






if __name__ == "__main__":
    asyncio.run(main())