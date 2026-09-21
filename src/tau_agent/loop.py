from collections.abc import AsyncIterator,AsyncGenerator

from asyncio import CancelledError
from tau_agent.cancellation import CancellationToken
from tau_agent.tools import execute_tool_call
from tau_agent.messages import AgentMessage,ToolResultMessage
from tau_agent.messages import AssistantMessage, UserMessage, ToolCall
from tau_agent.tools import AgentTool
from tau_agent.provider import ModelProvider
from tau_agent.provider_events import (
    AssistantDoneEvent,
)
from tau_agent.events import(
    AgentEvent,
    AgentStartEvent,
    AgentEndEvent,
    MessageUpdateEvent,
    ToolExecutionStartEvent,
    ToolExecutionEndEvent,
)
from contextlib import aclosing

async def run_agent_loop(
        *,
        provider: ModelProvider,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        prompt: UserMessage,
        max_turns: int = 10,
        signal: CancellationToken | None = None,
)-> AsyncGenerator[AgentEvent, None]:
    if max_turns < 1:
        raise ValueError("max_turns 必须至少为 1")
    # 把 prompt 追加到 messages
    messages.append(prompt)
    yield AgentStartEvent()
    turn = 0
    try:
        while True:
            if signal is not None and signal.is_cancelled():
                raise CancelledError("代理运行已取消")
            if turn >= max_turns:
                raise RuntimeError(f"已达到最大轮数：{max_turns}")

            turn += 1
            assistant: AssistantMessage | None = None
            provider_stream = provider.stream_response(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
            )
            async with aclosing(provider_stream):
                async for event in provider_stream:
                    if signal is not None and signal.is_cancelled():
                        raise CancelledError("代理运行已取消")
                    if isinstance(event, AssistantDoneEvent):
                        # 把完成事件中的最终消息追加到 messages
                        assistant = event.message
                        messages.append(event.message)

                    # 向消费者产出当前 event
                    yield MessageUpdateEvent(assistant_message_event=event)

            if assistant is None:
                raise RuntimeError("Provider 没有返回完成事件")
            calls = [
                block
                for block in assistant.content
                if isinstance(block, ToolCall)
            ]
            if not calls:
                break
            for index, call in enumerate(calls):
                yield ToolExecutionStartEvent(call=call)

                if signal is not None and signal.is_cancelled():
                    for pending_call in calls[index:]:
                        result = ToolResultMessage(
                            tool_call_id=pending_call.id,
                            tool_name=pending_call.name,
                            content=f"已取消执行 {pending_call.name} 工具",
                            is_error=True,
                        )
                        messages.append(result)
                        yield ToolExecutionEndEvent(result=result)
                    raise CancelledError("代理运行已取消")

                result = await execute_tool_call(call, tools)
                messages.append(result)
                yield ToolExecutionEndEvent(result=result)
    except CancelledError:
        yield AgentEndEvent(reason="cancelled")
        raise
    except Exception as exc:
        yield AgentEndEvent(
            reason="error",
            error_message=str(exc),
        )
        raise
    else:
        yield AgentEndEvent(reason="completed")
