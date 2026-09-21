from tau_agent.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    UserMessage,
    ToolResultMessage
)
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
import httpx

from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_agent.tools import AgentTool
@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""
class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API Key 不能为空")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def stream_response(
            self,
            *,
            model: str,
            system: str,
            messages: list[AgentMessage],
            tools: list[AgentTool],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        tool_call_deltas: list[ToolCallDelta] = []

        body = build_request_body(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
        )
        text_parts: list[str] = []
        received_done = False

        async with httpx.AsyncClient(
                transport=self._transport,
                timeout=60.0,
        ) as client:
            async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "text/event-stream",
                    },
                    json=body,
            ) as response:
                response.raise_for_status()
                yield AssistantStartEvent()

                async for line in response.aiter_lines():
                    data = extract_sse_data(line)

                    if data is None:
                        continue

                    if data == "[DONE]":
                        received_done = True
                        break

                    text_delta = parse_text_delta(data)
                    if text_delta is not None:
                        text_parts.append(text_delta)
                        yield TextDeltaEvent(delta=text_delta)

                    tool_call_deltas.extend(parse_tool_call_deltas(data))

        if not received_done:
            raise RuntimeError("DeepSeek 流未正常结束")

        content: list[TextContent | ToolCall] = []

        text = "".join(text_parts)
        if text:
            content.append(TextContent(text=text))

        content.extend(build_tool_calls(tool_call_deltas))

        if not content:
            raise RuntimeError("DeepSeek 响应没有文本或工具调用")

        yield AssistantDoneEvent(
            message=AssistantMessage(content=content)
        )




def build_tools(tools: list[AgentTool]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
def build_request_body(
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": model,
        "messages": build_messages(system, messages),
        "stream": True,
    }

    if tools:
        body["tools"] = build_tools(tools)

    return body
def build_messages(
    system: str,
    messages: list[AgentMessage],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = [
        {"role": "system", "content": system}
    ]

    for message in messages:
        if isinstance(message, UserMessage):
            # 追加 role="user"、content=message.content 的字典
            result.append({"role": "user", "content": message.content})



        elif isinstance(message, AssistantMessage):
            text = "".join(
                block.text
                for block in message.content
                if isinstance(block, TextContent)
            )
            calls = [
                block
                for block in message.content
                if isinstance(block, ToolCall)
            ]
            assistant_data: dict[str, object] = {
                "role": "assistant",
                "content": text or None,
            }
            if calls:
                assistant_data["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments,
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for call in calls
                ]
            result.append(assistant_data)
        elif isinstance(message, ToolResultMessage):
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )


    return result
def extract_sse_data(line: str) -> str | None:
    if not line.startswith("data:"):
        return None

    return line.removeprefix("data:").strip()
def parse_tool_call_deltas(data: str) -> list[ToolCallDelta]:
    value = json.loads(data)

    if not isinstance(value, dict):
        return []

    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        return []

    choice = choices[0]
    if not isinstance(choice, dict):
        return []

    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return []

    raw_calls = delta.get("tool_calls")
    if raw_calls is None:
        return []

    if not isinstance(raw_calls, list):
        raise ValueError("DeepSeek tool_calls 必须是列表")

    result: list[ToolCallDelta] = []

    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ValueError("DeepSeek 工具调用增量格式错误")

        index = raw_call.get("index")
        if not isinstance(index, int):
            raise ValueError("DeepSeek 工具调用增量缺少 index")

        call_id = raw_call.get("id")
        if not isinstance(call_id, str):
            call_id = None

        name: str | None = None
        arguments = ""

        function = raw_call.get("function")
        if isinstance(function, dict):
            raw_name = function.get("name")
            if isinstance(raw_name, str):
                name = raw_name

            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, str):
                arguments = raw_arguments

        result.append(
            ToolCallDelta(
                index=index,
                id=call_id,
                name=name,
                arguments=arguments,
            )
        )

    return result
def build_tool_calls(
    deltas: list[ToolCallDelta],
) -> list[ToolCall]:
    call_ids: dict[int, str] = {}
    name_parts: dict[int, list[str]] = {}
    argument_parts: dict[int, list[str]] = {}
    indexes: set[int] = set()

    for delta in deltas:
        indexes.add(delta.index)

        if delta.id is not None:
            existing_id = call_ids.get(delta.index)
            if existing_id is not None and existing_id != delta.id:
                raise ValueError("DeepSeek 工具调用 ID 前后不一致")
            call_ids[delta.index] = delta.id

        if delta.name is not None:
            name_parts.setdefault(delta.index, []).append(delta.name)

        if delta.arguments:
            argument_parts.setdefault(delta.index, []).append(
                delta.arguments
            )

    result: list[ToolCall] = []

    for index in sorted(indexes):
        call_id = call_ids.get(index)
        name = "".join(name_parts.get(index, []))
        arguments_text = "".join(
            argument_parts.get(index, [])
        ) or "{}"

        if call_id is None:
            raise ValueError("DeepSeek 工具调用缺少 ID")

        if not name:
            raise ValueError("DeepSeek 工具调用缺少名称")

        arguments = json.loads(arguments_text)
        if not isinstance(arguments, dict):
            raise ValueError("DeepSeek 工具调用参数必须是 JSON 对象")

        if not all(isinstance(key, str) for key in arguments):
            raise ValueError("DeepSeek 工具调用参数键必须是字符串")

        result.append(
            ToolCall(
                id=call_id,
                name=name,
                arguments=arguments,
            )
        )

    return result
def parse_text_delta(data: str) -> str | None:
    value = json.loads(data)

    if not isinstance(value, dict):
        return None

    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    choice = choices[0]
    if not isinstance(choice, dict):
        return None

    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return None

    content = delta.get("content")
    if not isinstance(content, str) or not content:
        return None

    return content
