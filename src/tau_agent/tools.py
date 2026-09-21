from typing import Protocol

from tau_agent.messages import ToolCall, ToolResultMessage

class AgentTool(Protocol):
    name: str
    description: str
    parameters: dict[str, object]

    async def execute(self, arguments: dict[str, object]) -> str:
        ...

async def execute_tool_call(
    call: ToolCall,
    tools: list[AgentTool],
) -> ToolResultMessage:
    tool_by_name = {tool.name: tool for tool in tools}
    tool = tool_by_name.get(call.name)

    if tool is None:
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=f"未知工具：{call.name}",
            is_error=True,
        )
    try:
        result_text = await tool.execute(arguments=call.arguments)
    except Exception as exc:
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=str(exc),
            is_error=True,
        )

    return ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content=result_text,
    )
