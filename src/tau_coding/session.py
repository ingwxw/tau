from collections.abc import AsyncGenerator
from contextlib import aclosing
from pathlib import Path

from tau_agent.events import AgentEvent
from tau_agent.harness import AgentHarness
from tau_agent.provider import ModelProvider
from tau_agent.session import SessionStorage
from tau_coding.tools import ReadFileTool


class CodingSession:
    def __init__(
        self,
        *,
        project_dir: Path,
        harness: AgentHarness,
    ) -> None:
        resolved_dir = project_dir.expanduser().resolve()

        if not resolved_dir.is_dir():
            raise ValueError(f"项目目录不存在或不是目录：{resolved_dir}")

        self._project_dir = resolved_dir
        self._harness = harness
    async def prompt(self, content: str) -> AsyncGenerator[AgentEvent, None]:
        async with aclosing(self._harness.prompt(content)) as stream:
            async for event in stream:
                yield event

    def cancel(self) -> None:
        self._harness.cancel()
    @property
    def project_dir(self) -> Path:
        return self._project_dir
def create_coding_session(
    *,
    project_dir: Path,
    provider: ModelProvider,
    model: str,
    system: str,
    session_storage: SessionStorage | None = None,
) -> CodingSession:
    project_dir = project_dir.expanduser().resolve()

    # 使用 project_dir 创建 ReadFileTool
    read_file_tool = ReadFileTool(project_dir)

    harness = AgentHarness(
        provider=provider,
        model=model,
        system=system,
        tools=[read_file_tool,],
        session_storage=session_storage,
    )
    return CodingSession(
        project_dir=project_dir,
        harness=harness,
    )
