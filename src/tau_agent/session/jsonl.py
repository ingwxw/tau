"""Strict JSONL encoding for session entries."""

from __future__ import annotations

import json
from typing import Any

from tau_agent.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tau_agent.session.entries import MessageEntry, SessionEntry


class SessionJsonlError(ValueError):
    pass


def _message_to_dict(message: AgentMessage) -> dict[str, object]:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.content}

    if isinstance(message, AssistantMessage):
        content: list[dict[str, object]] = []
        for block in message.content:
            if isinstance(block, TextContent):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolCall):
                content.append(
                    {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.arguments,
                    }
                )
            else:
                raise SessionJsonlError(
                    f"不支持的 Assistant 内容块：{type(block).__name__}"
                )
        return {"role": "assistant", "content": content}

    if isinstance(message, ToolResultMessage):
        return {
            "role": "tool_result",
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "content": message.content,
            "is_error": message.is_error,
        }

    raise SessionJsonlError(
        f"不支持的消息类型：{type(message).__name__}"
    )


def _message_from_dict(value: Any) -> AgentMessage:
    if not isinstance(value, dict):
        raise SessionJsonlError("message 必须是对象")

    role = value.get("role")
    if role == "user":
        user_content = value.get("content")
        if not isinstance(user_content, str):
            raise SessionJsonlError("UserMessage.content 必须是字符串")
        return UserMessage(content=user_content)

    if role == "assistant":
        raw_content = value.get("content")
        if not isinstance(raw_content, list):
            raise SessionJsonlError("AssistantMessage.content 必须是列表")

        assistant_blocks: list[TextContent | ToolCall] = []
        for block in raw_content:
            if not isinstance(block, dict):
                raise SessionJsonlError("Assistant 内容块必须是对象")

            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise SessionJsonlError("TextContent.text 必须是字符串")
                assistant_blocks.append(TextContent(text=text))
            elif block_type == "tool_call":
                call_id = block.get("id")
                name = block.get("name")
                arguments = block.get("arguments")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    raise SessionJsonlError("ToolCall.id/name 必须是字符串")
                if not isinstance(arguments, dict):
                    raise SessionJsonlError("ToolCall.arguments 必须是对象")
                assistant_blocks.append(
                    ToolCall(
                        id=call_id,
                        name=name,
                        arguments=arguments,
                    )
                )
            else:
                raise SessionJsonlError(
                    f"未知的 Assistant 内容块类型：{block_type!r}"
                )
        return AssistantMessage(content=assistant_blocks)

    if role == "tool_result":
        tool_call_id = value.get("tool_call_id")
        tool_name = value.get("tool_name")
        tool_content = value.get("content")
        is_error = value.get("is_error", False)
        if not isinstance(tool_call_id, str) or not isinstance(tool_name, str):
            raise SessionJsonlError("ToolResultMessage id/name 必须是字符串")
        if not isinstance(tool_content, str) or not isinstance(is_error, bool):
            raise SessionJsonlError("ToolResultMessage 字段类型错误")
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=tool_content,
            is_error=is_error,
        )

    raise SessionJsonlError(f"未知的消息 role：{role!r}")


def entry_to_dict(entry: SessionEntry) -> dict[str, object]:
    return {
        "type": entry.type,
        "id": entry.id,
        "parent_id": entry.parent_id,
        "timestamp": entry.timestamp,
        "message": _message_to_dict(entry.message),
    }


def entry_to_json_line(entry: SessionEntry) -> str:
    return json.dumps(
        entry_to_dict(entry),
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"


def entry_from_dict(value: Any) -> MessageEntry:
    if not isinstance(value, dict):
        raise SessionJsonlError("session entry 必须是对象")
    if value.get("type") != "message":
        raise SessionJsonlError(f"未知的 session entry type：{value.get('type')!r}")

    entry_id = value.get("id")
    parent_id = value.get("parent_id")
    timestamp = value.get("timestamp")
    if not isinstance(entry_id, str):
        raise SessionJsonlError("session entry.id 必须是字符串")
    if parent_id is not None and not isinstance(parent_id, str):
        raise SessionJsonlError("session entry.parent_id 类型错误")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        raise SessionJsonlError("session entry.timestamp 必须是数字")

    return MessageEntry(
        message=_message_from_dict(value.get("message")),
        id=entry_id,
        parent_id=parent_id,
        timestamp=float(timestamp),
    )


def entry_from_json_line(
    line: str,
    *,
    line_number: int | None = None,
) -> MessageEntry:
    location = f"（第 {line_number} 行）" if line_number is not None else ""
    try:
        return entry_from_dict(json.loads(line))
    except (json.JSONDecodeError, SessionJsonlError, TypeError) as exc:
        if isinstance(exc, SessionJsonlError):
            raise SessionJsonlError(f"无效的 session entry{location}：{exc}") from exc
        raise SessionJsonlError(f"无效的 JSONL{location}：{exc}") from exc


def entries_from_json_lines(lines: list[str]) -> list[MessageEntry]:
    entries: list[MessageEntry] = []
    for index, line in enumerate(lines, start=1):
        if line.strip():
            entries.append(entry_from_json_line(line, line_number=index))
    return entries
