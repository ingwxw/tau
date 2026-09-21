from typing import TextIO

from tau_agent.events import AgentEvent, MessageUpdateEvent, AgentEndEvent
from tau_agent.provider_events import AssistantDoneEvent, TextDeltaEvent
from tau_agent.events import (
    ToolExecutionStartEvent,
    ToolExecutionEndEvent,
)

class PlainRenderer:
    def __init__(self, output: TextIO) -> None:
        self._output = output
        self._line_open = False

    def _finish_line(self) -> None:
        if self._line_open:
            print(file=self._output, flush=True)
            self._line_open = False

    def render(self, event: AgentEvent) -> None:

        if isinstance(event, MessageUpdateEvent):
            model_event = event.assistant_message_event

            if isinstance(model_event, TextDeltaEvent):
                # TODO：输出增量文字，不换行，并立即刷新
                print(
                    model_event.delta,
                    end="",
                    flush=True,
                    file=self._output,
                )
                if model_event.delta:
                    self._line_open = not model_event.delta.endswith("\n")

            elif isinstance(model_event, AssistantDoneEvent):
                self._finish_line()
        elif isinstance(event, ToolExecutionStartEvent):
            self._finish_line()
            print(
                f"[工具开始] {event.call.name}",
                file=self._output,
                flush=True,
            )

        elif isinstance(event, ToolExecutionEndEvent):
            self._finish_line()
            status = "失败" if event.result.is_error else "成功"
            print(
                f"[工具{status}] {event.result.tool_name}",
                file=self._output,
                flush=True,
            )
        elif isinstance(event, AgentEndEvent):
            self._finish_line()
            if event.reason == "cancelled":
                print("[已取消]", file=self._output, flush=True)
            elif event.reason == "error":
                print(
                    f"[运行失败] {event.error_message}",
                    file=self._output,
                    flush=True,
                )
