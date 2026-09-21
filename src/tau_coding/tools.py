from pathlib import Path
import asyncio
class ReadFileTool:
    name: str = "read"
    description: str = "读取 UTF-8 文本文件"
    parameters: dict[str, object] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"]
    }
    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir.expanduser().resolve()


    async def execute(self, arguments: dict[str, object]) -> str:
        path = arguments.get("path")
        if not isinstance(path, str):
            raise ValueError("路径必须是字符串")

        target = (self._project_dir/path).resolve()

        return await asyncio.to_thread(
            target.read_text,
            encoding="utf-8",
        )
