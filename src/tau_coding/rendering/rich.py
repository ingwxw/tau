from rich.console import Console

from tau_agent.events import (
    AgentEndEvent,
    AgentEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from tau_agent.provider_events import (
    AssistantDoneEvent,
    TextDeltaEvent,
)


class RichRenderer:
    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._line_open = False

    def _finish_line(self) -> None:
        if self._line_open:
            self._console.print()
            self._line_open = False

    def render(self, event: AgentEvent) -> None:
        if isinstance(event, MessageUpdateEvent):
            provider_event = event.assistant_message_event

            if isinstance(provider_event, TextDeltaEvent):
                self._console.print(
                    provider_event.delta,
                    end="",
                    markup=False,
                    highlight=False,
                )
                self._line_open = not provider_event.delta.endswith("\n")

            elif isinstance(provider_event, AssistantDoneEvent):
                self._finish_line()

        elif isinstance(event, ToolExecutionStartEvent):
            self._finish_line()
            self._console.print(
                f"⚙ 正在执行 {event.call.name}",
                style="cyan",
            )

        elif isinstance(event, ToolExecutionEndEvent):
            self._finish_line()

            if event.result.is_error:
                self._console.print(
                    f"✗ {event.result.tool_name}：{event.result.content}",
                    style="bold red",
                )
            else:
                self._console.print(
                    f"✓ {event.result.tool_name}",
                    style="green",
                )

        elif isinstance(event, AgentEndEvent):
            self._finish_line()

            if event.reason == "cancelled":
                self._console.print("已取消", style="yellow")
            elif event.reason == "error":
                self._console.print(
                    f"运行失败：{event.error_message}",
                    style="bold red",
                )
