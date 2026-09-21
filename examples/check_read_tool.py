import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path

from tau_agent.messages import ToolCall
from tau_agent.tools import AgentTool, execute_tool_call
from tau_coding.tools import ReadFileTool


async def main():
    with TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        (project_dir / "sample.txt").write_text(
            "你好，Tau", encoding="utf-8"
        )
        read_tool: AgentTool = ReadFileTool(project_dir)
        call1: ToolCall = ToolCall(
            id="call_1",
            name=read_tool.name,
            arguments={
                "path": "sample.txt",
            }
        )
        result1 = await execute_tool_call(
            call1,
            tools=[read_tool,]
        )
        assert result1.content == "你好，Tau"
        assert result1.tool_call_id == "call_1"
        assert result1.is_error is False
        call2: ToolCall = ToolCall(
            id="call_2",
            name=read_tool.name,
            arguments={
                "path": "missing.txt",
            }
        )
        result2 = await execute_tool_call(
            call2,
            tools=[read_tool,]
        )
        assert result2.tool_call_id == "call_2"
        assert result2.is_error is True
        print("文件读取工具检查通过")




if __name__ == "__main__":
    asyncio.run(main())
