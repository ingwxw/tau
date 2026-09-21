"""流式过程中的界面不变量。

这里钉的是两类会静默出错、肉眼看又不明显的东西：

1. 模型静默期（``AssistantStartEvent`` 之后、第一个字之前）界面上必须有
   活动指示。真实模型在这段要等好几秒，只有一个光秃秃的 ``⏺`` 会像卡死。
2. 消息行的实际高度必须等于正文列的高度。``Horizontal`` / ``Vertical``
   的默认高度是 ``1fr`` 而不是 ``auto``，一旦行被撑开，多出来的部分是
   被 ``overflow: hidden`` 裁掉的——不报错，只是中间空一大片。

``check_tui_render.py`` 管的是内容对不对（标记、摘要、错误），这里只管
时序和布局。
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from tau_agent.harness import AgentHarness
from tau_agent.messages import AgentMessage, AssistantMessage, TextContent
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_ai.fake import FakeToolProvider
from tau_coding.session import CodingSession
from tau_coding.tui.app import TauTuiApp
from tau_coding.tui.widgets import SpinnerLine, ToolCallBlock

#: 160 格宽（CJK 每字 2 格），在 40/72/110 三种宽度下都必然折行。
LONG_TEXT = "第一句。" * 20


class SlowProvider:
    """``AssistantStartEvent`` 之后先静默一阵再吐字，模拟模型的思考期。"""

    def __init__(self, *, delay: float = 0.5, text: str = "你好") -> None:
        self._delay = delay
        self._text = text

    async def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[object],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        yield AssistantStartEvent()
        await asyncio.sleep(self._delay)
        for char in self._text:
            yield TextDeltaEvent(char)
        yield AssistantDoneEvent(AssistantMessage([TextContent(self._text)]))


class SlowEchoTool:
    """匹配 ``FakeToolProvider`` 的 ``echo`` 调用，故意跑得慢。"""

    name = "echo"
    description = "回显文本"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def __init__(self, *, delay: float = 0.5) -> None:
        self._delay = delay

    async def execute(self, arguments: dict[str, object]) -> str:
        await asyncio.sleep(self._delay)
        return "你好"


def make_app(*, provider: object, tools: list[object] | None = None) -> TauTuiApp:
    harness = AgentHarness(
        provider=provider,  # type: ignore[arg-type]
        model="fake",
        system="test",
        tools=tools or [],  # type: ignore[arg-type]
    )
    return TauTuiApp(
        CodingSession(project_dir=Path.cwd(), harness=harness),
        provider_name="fake",
        model="fake",
    )


async def send(app: TauTuiApp, pilot, content: str) -> None:
    app.query_one("#prompt").text = content
    await pilot.press("enter")


#: 两列行。``.tool-head`` / ``.tool-result`` 是重点：它们没有在 CSS 里写
#: ``height: auto``，完全依赖容器自己的默认值——``HorizontalGroup`` 是 auto，
#: ``Horizontal`` 是 ``1fr``。换错基类时肉眼看只是「中间空了一大片」。
ROW_SELECTORS = ".user-message, .assistant-message, .tool-head, .tool-result"


def check_rows_are_not_stretched(app: TauTuiApp) -> None:
    """行高必须由正文列决定，不能被默认的 ``height: 1fr`` 撑开。"""
    rows = list(app.query_one("#messages").query(ROW_SELECTORS))
    assert rows, "这一轮应该至少有一行消息"

    for row in rows:
        body = row.query_one(".body")
        label = type(row).__name__ + "".join(f".{name}" for name in sorted(row.classes))
        assert row.region.height == body.region.height, (
            f"{label} 行高 {row.region.height} != 正文高 {body.region.height}，"
            f"说明行被默认的 height:1fr 撑开了"
        )
        # 正文列必须真的分到宽度，否则是 1fr 被固定宽兄弟挤成 0 的经典症状。
        mark = row.query_one(".mark, .result-mark")
        assert body.region.width > mark.region.width, (
            f"正文列宽 {body.region.width} 不大于标记列宽 {mark.region.width}"
        )


async def check_thinking_indicator() -> None:
    app = make_app(provider=SlowProvider(delay=0.5))
    async with app.run_test(size=(72, 20)) as pilot:
        await pilot.pause()
        await send(app, pilot, "你好")
        await pilot.pause(0.15)

        # 静默期：有且只有一个 spinner，且没有空的助手行占位。
        spinners = app.query(SpinnerLine)
        assert len(spinners) == 1, f"模型静默期应有且只有一个 spinner，实际 {len(spinners)}"
        assert spinners.first().is_animating
        assert "正在思考" in str(spinners.first().render())

        visible = [m for m in app.query(".assistant-message") if m.display]
        assert not visible, "第一个字到达之前不该挂助手消息行"

        await pilot.pause(0.7)
        assert not app.query(SpinnerLine), "开始吐字后 spinner 应收起"
        assert len([m for m in app.query(".assistant-message") if m.display]) == 1


async def check_tool_spinner_is_last() -> None:
    """工具执行中 spinner 必须在最下面，否则会留在工具块上方。"""
    app = make_app(provider=FakeToolProvider(), tools=[SlowEchoTool(delay=0.5)])
    async with app.run_test(size=(72, 20)) as pilot:
        await pilot.pause()
        await send(app, pilot, "跑一下 echo")
        await pilot.pause(0.15)

        children = list(app.query_one("#messages").children)
        assert isinstance(children[-1], SpinnerLine), (
            f"工具执行中最后一行应是 spinner，实际是 {type(children[-1]).__name__}"
        )
        assert "正在执行 echo" in str(children[-1].render())
        assert isinstance(children[-2], ToolCallBlock)

        # 长工具跑完之前一直要有动的东西。
        await pilot.pause(0.2)
        assert app.query(SpinnerLine), "工具没跑完 spinner 不该消失"

        await pilot.pause(0.8)
        assert not app.query(SpinnerLine), "回合结束后 spinner 必须收起"

        # 工具块是唯一两个「靠容器默认高度」的两列行，必须一起量。
        check_rows_are_not_stretched(app)


async def check_auto_height_while_streaming() -> None:
    """折行的消息行高度要跟着文本长，不能被裁掉。"""
    for width, height in ((40, 20), (72, 24), (110, 32)):
        app = make_app(provider=SlowProvider(delay=0.05, text=LONG_TEXT))
        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause()
            await send(app, pilot, "写点长的")
            await pilot.pause(0.6)

            check_rows_are_not_stretched(app)

            assistant = [m for m in app.query(".assistant-message") if m.display][-1]
            body = assistant.query_one(".body")
            assert assistant.body_text == LONG_TEXT, "流式增量拼接丢字了"
            # 折行内容必须真的占多行——高度停在 1 说明被裁了。
            assert body.region.height > 1, (
                f"width={width} 时折行正文只有 {body.region.height} 行"
            )

            assert app.query_one("#composer").region.height == 3
            assert app.query_one("#prompt").region.height == 1


async def check_render_error_is_labelled() -> None:
    """界面自身的异常不能报成「运行失败」。"""
    app = make_app(provider=SlowProvider(delay=0.05))

    async def boom(event: object) -> None:
        raise RuntimeError("布局炸了")

    app._render_event = boom  # type: ignore[method-assign]

    async with app.run_test(size=(72, 20)) as pilot:
        await pilot.pause()
        await send(app, pilot, "你好")
        await pilot.pause(0.4)

        hint = str(app.query_one("#hint").render())
        assert "界面渲染失败" in hint, hint
        assert "运行失败" not in hint, f"界面异常被报成了运行失败：{hint}"


async def main() -> None:
    await check_thinking_indicator()
    await check_tool_spinner_is_last()
    await check_auto_height_while_streaming()
    await check_render_error_is_labelled()
    print("TUI 流式布局检查通过")


if __name__ == "__main__":
    asyncio.run(main())
