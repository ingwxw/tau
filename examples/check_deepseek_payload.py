from tau_ai.deepseek import build_request_body, build_messages, ToolCallDelta, parse_tool_call_deltas, build_tool_calls
from tau_agent.messages import UserMessage, AssistantMessage, TextContent, ToolCall, ToolResultMessage
from tau_ai.deepseek import extract_sse_data
class FakeTool:
    name = "read"
    description = "读取文件"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict[str, object]) -> str:
        return ""
assert extract_sse_data("") is None
assert extract_sse_data(": keep-alive") is None
assert extract_sse_data("data: {\"value\": 1}") == '{"value": 1}'
assert extract_sse_data("data:[DONE]") == "[DONE]"

from tau_ai.deepseek import parse_text_delta

assert parse_text_delta(
    '{"choices":[{"delta":{"content":"你"}}]}'
) == "你"

assert parse_text_delta(
    '{"choices":[{"delta":{"role":"assistant"}}]}'
) is None

assert parse_text_delta(
    '{"choices":[{"finish_reason":"stop","delta":{}}]}'
) is None

assert parse_text_delta('{"choices":[]}') is None
print("DeepSeek SSE 行解析检查通过")
body = build_request_body(
    model="deepseek-chat",
    system="你是一个助手",
    messages=[UserMessage(content="你好")],
    tools=[FakeTool()],
)

assert body == {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好"},
    ],
    "stream": True,
    "tools":[
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取文件",
            "parameters": FakeTool.parameters,
        },
    }
]

}
body_without_tools = build_request_body(
    model="deepseek-chat",
    system="你是一个助手",
    messages=[UserMessage(content="你好")],
    tools=[],
)
messages = [
    AssistantMessage(
        content=[
            TextContent(text="我先读取文件"),
            ToolCall(
                id="call_1",
                name="read",
                arguments={"path": "你好.txt"},
            ),
        ]
    ),
    ToolResultMessage(
        tool_call_id="call_1",
        tool_name="read",
        content="文件内容",
    ),
]
assert build_messages(
    system="助手",
    messages=messages ) == [
    {"role": "system", "content": "助手"},
    {
        "role": "assistant",
        "content": "我先读取文件",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "read",
                    "arguments": '{"path": "你好.txt"}',
                },
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "文件内容",
    },
]
first = parse_tool_call_deltas(
    """
    {
      "choices": [{
        "delta": {
          "tool_calls": [{
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {
              "name": "read",
              "arguments": ""
            }
          }]
        }
      }]
    }
    """
)

second = parse_tool_call_deltas(
    """
    {
      "choices": [{
        "delta": {
          "tool_calls": [{
            "index": 0,
            "function": {
              "arguments": "{\\"path\\":\\"README.md\\"}"
            }
          }]
        }
      }]
    }
    """
)

assert first == [
    ToolCallDelta(index=0, id="call_1", name="read", arguments="")
]
assert second == [
    ToolCallDelta(
        index=0,
        arguments='{"path":"README.md"}',
    )
]
assert "tools" not in body_without_tools

deltas = [
    ToolCallDelta(
        index=0,
        id="call_1",
        name="read",
        arguments='{"path":',
    ),
    ToolCallDelta(
        index=0,
        arguments='"README.md"}',
    ),
]

assert build_tool_calls(deltas) == [
    ToolCall(
        id="call_1",
        name="read",
        arguments={"path": "README.md"},
    )
]
try:
    build_tool_calls(
        [
            ToolCallDelta(
                index=0,
                id="call_1",
                name="read",
                arguments="[]",
            )
        ]
    )
except ValueError as exc:
    assert str(exc) == "DeepSeek 工具调用参数必须是 JSON 对象"
else:
    raise AssertionError("非对象工具参数应该被拒绝")
print("DeepSeek 请求体检查通过")
