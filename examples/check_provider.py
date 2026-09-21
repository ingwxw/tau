import asyncio
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AssistantMessage
from tau_agent.messages import AgentMessage
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_agent.messages import UserMessage,TextContent
from tau_agent.provider import ModelProvider
from tau_ai.fake import FakeProvider
from tau_agent.events import MessageUpdateEvent

async def main() -> None:
    provider: ModelProvider = FakeProvider()
    messages: list[AgentMessage] = []

    stream = run_agent_loop(
        provider=provider,
        model="fake",
        system="你是一个助手",
        messages=messages,
        tools=[],
        prompt=UserMessage(content="你好"),
    )
    received_text = ""
    async for agent_event in stream:
        if not isinstance(agent_event, MessageUpdateEvent):
            continue

        event = agent_event.assistant_message_event
        if isinstance(event, AssistantStartEvent):
            print("模型：", end="", flush=True)
        elif isinstance(event, TextDeltaEvent):
            received_text += event.delta
            print(event.delta, end="", flush=True)
        elif isinstance(event, AssistantDoneEvent):
            print()
            final_text = "".join(
                block.text
                for block in event.message.content
                if isinstance(block, TextContent)
            )
            assert received_text == final_text, "增量文本与最终消息不一致"
            assert final_text == "你好", "回复与预设内容不一致"
            print("事件流内容检查通过")
    assert len(messages) == 2
    assert isinstance(messages[0], UserMessage)
    assert isinstance(messages[1], AssistantMessage)
    print("Loop 消息历史检查通过")
asyncio.run(main())
