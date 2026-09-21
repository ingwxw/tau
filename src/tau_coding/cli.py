import argparse
import asyncio
import sys
from contextlib import aclosing
from pathlib import Path

from rich.console import Console

from tau_agent.session import JsonlSessionStorage
from tau_coding.provider_runtime import create_provider_runtime
from tau_coding.rendering.base import EventRenderer
from tau_coding.rendering.plain import PlainRenderer
from tau_coding.rendering.rich import RichRenderer
from tau_coding.session import CodingSession, create_coding_session


async def consume_prompt(
    session: CodingSession,
    renderer: EventRenderer,
    content: str,
) -> None:
    async with aclosing(session.prompt(content)) as stream:
        async for event in stream:
            renderer.render(event)
async def run(
        prompt: str | None,
        interactive: bool,
        project_dir: Path,
        provider_name: str,
        model: str | None,
        renderer_name: str,
        session_file: Path | None,
) -> None:
    runtime = create_provider_runtime(
        provider_name,
        model,
    )

    session = create_coding_session(
        project_dir=project_dir,
        provider=runtime.provider,
        model=runtime.model,
        system="你是一个编码助手。请使用提供的工具完成用户任务。",
        session_storage=(
            JsonlSessionStorage(session_file)
            if session_file is not None
            else None
        ),
    )

    renderer: EventRenderer

    if renderer_name == "plain":
        renderer = PlainRenderer(sys.stdout)
    elif renderer_name == "rich":
        renderer = RichRenderer(
            Console(file=sys.stdout)
        )
    else:
        raise ValueError(f"不支持的渲染器：{renderer_name}")

    if not interactive:
        assert prompt is not None
        await consume_prompt(session, renderer, prompt)
        return

    while True:
        try:
            content = await asyncio.to_thread(input, "你> ")
        except EOFError:
            break

        content = content.strip()

        if content in {"/exit", "/quit"}:
            break

        if not content:
            continue

        await consume_prompt(session, renderer, content)

def main() -> None:
    parser = argparse.ArgumentParser(description="Tau 编码助手")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--provider",
        choices=["fake", "deepseek"],
        default="fake",
    )
    parser.add_argument(
        "--model",
        default=None,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="发送给代理的消息",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="进入多轮交互模式",
    )
    parser.add_argument(
        "--renderer",
        choices=["plain", "rich"],
        default="rich",
    )
    parser.add_argument(
        "--session-file",
        type=Path,
        default=None,
        help="启用 JSONL 会话持久化并从该文件恢复",
    )
    args = parser.parse_args()
    if not args.interactive and args.prompt is None:
        parser.error("必须提供 prompt，或者使用 --interactive")
    try:
        asyncio.run(
            run(
                args.prompt,
                args.interactive,
                args.project,
                args.provider,
                args.model,
                args.renderer,
                args.session_file,
            )
        )
    except ValueError as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    main()
