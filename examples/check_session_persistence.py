import asyncio
import tempfile
from contextlib import aclosing
from pathlib import Path

from tau_agent.harness import AgentHarness
from tau_agent.messages import AssistantMessage, TextContent, UserMessage
from tau_agent.session import JsonlSessionStorage
from tau_ai.fake import FakeProvider


async def run_prompt(harness: AgentHarness, content: str) -> None:
    stream = harness.prompt(content)
    async with aclosing(stream):
        async for _event in stream:
            pass


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session.jsonl"

        first = AgentHarness(
            provider=FakeProvider(),
            model="fake",
            system="test",
            tools=[],
            session_storage=JsonlSessionStorage(path),
        )
        await run_prompt(first, "第一轮")

        second = AgentHarness(
            provider=FakeProvider(),
            model="fake",
            system="test",
            tools=[],
            session_storage=JsonlSessionStorage(path),
        )
        assert second.messages == (
            UserMessage("第一轮"),
            AssistantMessage([TextContent("你好")]),
        )

        await run_prompt(second, "第二轮")
        entries = JsonlSessionStorage(path).read_all()
        assert len(entries) == 4
        assert entries[1].parent_id == entries[0].id
        assert entries[2].parent_id == entries[1].id
        assert entries[3].parent_id == entries[2].id

    print("Session 持久化检查通过")


asyncio.run(main())
