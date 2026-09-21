import asyncio

from tau_agent.tools import AgentTool

class EchoTool:
    name = "echo"
    description = "用于原样返回文本内容"
    parameters: dict[str, object] = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict[str, object]) -> str:
        text = arguments.get("text")
        # TODO 1：如果 text 不是字符串，抛出 ValueError
        if not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        # TODO 2：返回 text
        return text

async def main():
    tool: AgentTool = EchoTool()
    result = await tool.execute({"text":"你好"})
    assert result == "你好"
    print("工具执行检查通过")

if __name__ == "__main__":
    asyncio.run(main())