import argparse
from pathlib import Path

from tau_agent.session import JsonlSessionStorage
from tau_coding.provider_runtime import create_provider_runtime
from tau_coding.session import create_coding_session
from tau_coding.tui.app import TauTuiApp


def main() -> None:
    parser = argparse.ArgumentParser(description="Tau Textual TUI")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--provider",
        choices=["fake", "deepseek"],
        default="fake",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--session-file",
        type=Path,
        default=None,
        help="启用 JSONL 会话持久化并从该文件恢复",
    )
    args = parser.parse_args()

    try:
        runtime = create_provider_runtime(args.provider, args.model)
        session = create_coding_session(
            project_dir=args.project,
            provider=runtime.provider,
            model=runtime.model,
            system=(
                "你是一个编码助手。请使用提供的工具完成用户任务。"
            ),
            session_storage=(
                JsonlSessionStorage(args.session_file)
                if args.session_file is not None
                else None
            ),
        )
    except ValueError as exc:
        parser.error(str(exc))

    TauTuiApp(
        session,
        provider_name=args.provider,
        model=runtime.model,
    ).run()


if __name__ == "__main__":
    main()
