import asyncio
from io import StringIO
from pathlib import Path

from tau_ai.fake import FakeProvider
from tau_coding.rendering.plain import PlainRenderer
from tau_coding.session import create_coding_session


async def main() -> None:
    output = StringIO()
    renderer = PlainRenderer(output)

    session = create_coding_session(
        project_dir=Path(__file__).resolve().parents[1],
        provider=FakeProvider(),
        model="fake",
        system="你是一个助手",
    )

    # TODO：消费 session.prompt("你好")
    # 将每个事件交给 renderer.render(event)
    async for event in session.prompt("你好"):
        renderer.render(event)

    assert output.getvalue() == "你好\n"
    print("print 前端链路检查通过")


if __name__ == "__main__":
    asyncio.run(main())