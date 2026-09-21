import asyncio
import json
from contextlib import aclosing

import httpx

from tau_ai.deepseek import DeepSeekProvider
from tau_agent.loop import run_agent_loop
from tau_agent.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


class FakeReadTool:
    name = "read"
    description = "读取文件"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    async def execute(
        self,
        arguments: dict[str, object],
    ) -> str:
        assert arguments == {"path": "README.md"}
        return "文件内容"


def make_sse(chunks: list[dict[str, object]]) -> bytes:
    lines = [
        f"data: {json.dumps(chunk, ensure_ascii=False)}"
        for chunk in chunks
    ]
    lines.append("data: [DONE]")

    return ("\n\n".join(lines) + "\n\n").encode()


request_bodies: list[dict[str, object]] = []


async def handle_request(
    request: httpx.Request,
) -> httpx.Response:
    body = json.loads(request.content)
    request_bodies.append(body)

    request_number = len(request_bodies)

    if request_number == 1:
        # 第一次调用模型时，历史中只有 system 和 user。
        assert [
            message["role"]
            for message in body["messages"]
        ] == ["system", "user"]

        assert body["tools"][0]["function"]["name"] == "read"

        content = make_sse(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read",
                                            "arguments": '{"path":',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "arguments": '"README.md"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
            ]
        )

        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=content,
        )

    if request_number == 2:
        # Loop 已经执行工具，因此第二次请求必须带上
        # assistant 工具调用和 tool 执行结果。
        assert [
            message["role"]
            for message in body["messages"]
        ] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]

        assistant_data = body["messages"][2]
        tool_data = body["messages"][3]

        tool_call_data = assistant_data["tool_calls"][0]

        assert tool_call_data["id"] == "call_1"
        assert tool_call_data["function"]["name"] == "read"
        assert json.loads(
            tool_call_data["function"]["arguments"]
        ) == {
            "path": "README.md",
        }

        assert tool_data == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "文件内容",
        }

        content = make_sse(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "content": "文件内容是：",
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "content": "文件内容",
                            }
                        }
                    ]
                },
            ]
        )

        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            content=content,
        )

    raise AssertionError(
        f"模型不应该被调用第 {request_number} 次"
    )


async def main() -> None:
    provider = DeepSeekProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handle_request),
    )

    messages: list[AgentMessage] = []
    events = []

    stream = run_agent_loop(
        provider=provider,
        model="deepseek-chat",
        system="你是一个编码助手",
        messages=messages,
        tools=[FakeReadTool()],
        prompt=UserMessage(content="读取 README.md"),
    )

    async with aclosing(stream):
        async for event in stream:
            events.append(event)

    assert len(request_bodies) == 2

    assert messages == [
        UserMessage(content="读取 README.md"),
        AssistantMessage(
            content=[
                ToolCall(
                    id="call_1",
                    name="read",
                    arguments={"path": "README.md"},
                )
            ]
        ),
        ToolResultMessage(
            tool_call_id="call_1",
            tool_name="read",
            content="文件内容",
        ),
        AssistantMessage(
            content=[
                TextContent(
                    text="文件内容是：文件内容",
                )
            ]
        ),
    ]

    assert events[-1].type == "agent_end"
    assert events[-1].reason == "completed"

    print("DeepSeek 工具调用闭环检查通过")


asyncio.run(main())