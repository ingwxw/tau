"""检查对话流的渲染：标记符号、Markdown、工具块、spinner、横幅降级。

用假 provider 跑完整回合，不依赖任何真实模型。
"""

import asyncio
from pathlib import Path

from rich.segment import Segment
from textual.content import Content
from textual.geometry import Region
from textual.style import Style as TuiStyle

from tau_agent.harness import AgentHarness
from tau_agent.messages import ToolCall
from tau_ai.fake import FakeToolProvider
from tau_coding.session import CodingSession
from tau_coding.tui.app import HINT_IDLE, TauTuiApp
from tau_coding.tui.markdown import render_markdown
from tau_coding.tui.theme import PERMISSION
from tau_coding.tui.widgets import (
    EXPANDED_LINES,
    SUMMARY_LIMIT,
    AssistantMessage,
    SpinnerLine,
    ToolCallBlock,
    format_tool_call,
    summarize_result,
)

ECHO_BODY = "你好\n第二行\n第三行"

#: 行数足够多，折叠与展开两种形态都能看出差别。
MANY_LINES = "\n".join(f"第 {index} 行" for index in range(1, 61))

MARKDOWN_SOURCE = (
    "看这段：\n"
    "\n"
    "```python\n"
    "def f():\n"
    '    s = "x"  # 注释\n'
    "    return 1\n"
    "```\n"
    "\n"
    "# 一级标题\n"
    "\n"
    "> 引用一行\n"
    "\n"
    "- 列表一\n"
    "- 列表二\n"
    "\n"
    "1. 有序一\n"
    "2. 有序二\n"
    "\n"
    "**粗体**与 `代码`。\n"
    "\n"
    "---\n"
)


class EchoTool:
    """回显工具，匹配 FakeToolProvider 发出的 ``echo`` 调用。"""

    name = "echo"
    description = "回显文本"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }

    def __init__(self, body: str = ECHO_BODY) -> None:
        self._body = body

    async def execute(self, arguments: dict[str, object]) -> str:
        return self._body


def make_app(*, tools: list[object]) -> TauTuiApp:
    harness = AgentHarness(
        provider=FakeToolProvider(),
        model="fake",
        system="test",
        tools=tools,  # type: ignore[arg-type]
    )
    return TauTuiApp(
        CodingSession(project_dir=Path.cwd(), harness=harness),
        provider_name="fake",
        model="fake",
    )


def styled_spans(content: Content) -> list[tuple[str, TuiStyle]]:
    """``Content`` 里 (文本, 样式) 对，留下有样式且非空白的那些。

    这一层查的是样式而不是像素，所以只看 span，不重新渲染——Markdown 的出口
    就是 ``Content``，绕开它去渲染等于绕过被测对象。
    """
    return [
        (piece, span.style)
        for span in content.spans
        if (piece := content.plain[span.start : span.end]).strip()
    ]


def widget_lines(widget: object, width: int, height: int) -> list[list[Segment]]:
    """渲染 widget 自身，走的是 Textual 真正的绘制路径。"""
    return widget.render_lines(Region(0, 0, width, height))  # type: ignore[attr-defined]


def check_pure_helpers() -> None:
    single = ToolCall(id="c1", name="read", arguments={"path": "src/a.py"})
    assert format_tool_call(single) == "read(src/a.py)"

    multi = ToolCall(id="c2", name="edit", arguments={"path": "a.py", "old": "b"})
    assert format_tool_call(multi) == "edit(path=a.py, old=b)"

    assert summarize_result("") == "(无输出)"
    assert summarize_result("单行") == "单行"
    # 折叠态必须自己说清楚「还有多少没显示、按哪个键展开」，否则那一行
    # 看起来就像全部输出。
    assert summarize_result(ECHO_BODY) == "你好 … +2 行 (ctrl+o 展开)"

    long_line = "x" * (SUMMARY_LIMIT + 50)
    summary = summarize_result(long_line)
    # 长行截断后还要挂上「+N 行」是不对的——它只有一行。
    assert len(summary) == SUMMARY_LIMIT + 1 and summary.endswith("…"), summary


def check_markdown_layer() -> None:
    """Markdown 层：字形、字重、配色逐条对齐 Claude Code 的 ``JT``。

    这一层的每一项都是「静默回退」型的：Rich 的出厂表现一样渲染得出来，只是
    居中标题、品红引用块、``•`` 列表、霓虹代码块。不逐条钉住的话，改
    ``markdown.TauMarkdown`` / ``CODE_STYLE_MAP`` 时会无声无息地退回去。
    """
    content = render_markdown(MARKDOWN_SOURCE, 60)
    text = content.plain

    assert "```" not in text, f"围栏没被吃掉：\n{text}"
    assert "def f():" in text and "return 1" in text, text
    assert "**" not in text, f"强调标记没被吃掉：\n{text}"
    assert "粗体" in text and "代码" in text, text

    # h1 默认居中，在跟着气泡宽度变化的对话流里会左右横跳。
    heading = [line for line in text.splitlines() if "一级标题" in line]
    assert heading, text
    assert heading[0].startswith("一级标题"), f"标题没有左对齐：{heading[0]!r}"

    styled = styled_spans(content)
    assert styled, "一个带样式的分段都没有，说明渲染路径变了，这条断言已经失效"

    def pieces(want: str) -> list[TuiStyle]:
        """纯文本恰好是 ``want`` 的那些分段的样式。"""
        return [style for piece, style in styled if piece == want]

    def colors(want: str) -> set[str | None]:
        """纯文本恰好是 ``want`` 的那些分段的前景色。"""
        return {
            style.foreground.hex if style.foreground is not None else None
            for style in pieces(want)
        }

    # 代码块铺底色是 Rich 从 pygments 主题的 background_color 取的。断言的是
    # 「没有任何分段被铺底色」，不写死具体颜色：``ANSISyntaxTheme`` 的背景样式
    # 本来就是空的，换成任何别的主题都会在这里露出来。
    painted = [style for _, style in styled if style.background is not None]
    assert not painted, f"有分段被铺了底色：{painted[:2]}"

    # h1 = bold + italic + underline，**且不带字色**。Claude Code 的标题分级靠
    # 字重不靠色相（``JT`` 里 h1 不带任何颜色），旧版本这里断言的是本项目的 TEXT。
    title = pieces("一级标题")
    assert title, f"标题没有样式：{styled[:6]}"
    assert (title[0].bold, title[0].italic, title[0].underline) == (True, True, True), (
        f"h1 不是粗体+斜体+下划线：{title[0]}"
    )
    assert title[0].foreground is None, f"h1 不该有字色：{title[0].foreground}"

    # 引用块：``▎`` + 空格，符号压暗、正文斜体。Rich 出厂是 ``▌`` 且整段只压暗。
    marker = pieces("▎ ")
    assert marker, f"引用块符号不是 ▎：{text!r}"
    assert marker[0].dim is True, "引用块符号没有压暗"
    assert marker[0].foreground is None and marker[0].italic is not True, (
        "▎ 只有 dim 一层，不该继承正文的字色和斜体"
    )
    quote = pieces("引用一行")
    assert quote and quote[0].italic is True, "引用块正文没有斜体"

    # 列表符号：``-`` 和 ``1.``，两个都不上色（Rich 出厂是 ``•`` 不带句点、
    # 且给符号加粗、给编号上青色）。
    assert len(pieces("- ")) == 2, f"无序列表符号不是 -：{text!r}"
    assert "1. 有序一" in text and "2. 有序二" in text, f"有序列表编号没有句点：{text!r}"
    for style in pieces("- ") + pieces("1. ") + pieces("2. "):
        assert style.foreground is None and style.bold is not True, (
            f"列表符号被上了色或加粗：{style}"
        )

    # ``hr`` 是字面量 ``---``，不是一条铺满整行的横线。
    assert "\n---" in text, f"hr 不是字面量 ---：{text!r}"

    # 行内代码用 Claude Code 的 ``permission``（``#b1b9f9``），不是底色。
    assert colors("代码") == {PERMISSION.upper()}, (
        f"行内代码配色不是 PERMISSION：{colors('代码')}"
    )

    # 代码块的字色是 **ANSI 具名色**：Claude Code 没有 RGB 配色表，它用的是 chalk
    # 的 blue/cyan/green/red/yellow/grey，也就是让终端自己的调色板决定颜色。
    # 正文里能出现的前景色因此是一个闭集——闭集之外的颜色只可能来自 Rich 的
    # DEFAULT_STYLES（magenta / cyan）或 pygments 的 monokai 真彩色
    # （#ff4689 / #66d9ef / #a6e22e）。
    allowed = {
        "ansi_blue",
        "ansi_cyan",
        "ansi_green",
        "ansi_red",
        "ansi_yellow",
        "ansi_bright_black",
        "ansi_bright_blue",
        PERMISSION.upper(),
    }
    used = {
        color.hex
        for _, style in styled
        for color in (style.foreground, style.background)
        if color is not None
    }
    assert used <= allowed, f"正文里出现了闭集之外的配色：{sorted(used - allowed)}"

    # 闭集断言只挡得住「多」，挡不住「整块掉色」——所以再逐个钉住 scope 映射。
    assert colors("def") == {"ansi_blue"}, f"关键字不是 blue：{colors('def')}"
    assert colors("f") == {"ansi_yellow"}, f"函数名不是 yellow：{colors('f')}"
    assert colors("x") == {"ansi_red"}, f"字符串不是 red：{colors('x')}"
    assert colors("# 注释") == {"ansi_green"}, f"注释不是 green：{colors('# 注释')}"
    assert colors("1") == {"ansi_green"}, f"数字不是 green：{colors('1')}"


async def check_assistant_markdown() -> None:
    """助手正文按 Markdown 渲染，但 body_text 保留原始源码。"""
    app = make_app(tools=[])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assistant = AssistantMessage()
        await app.query_one("#messages").mount(assistant)
        assistant.append_text(MARKDOWN_SOURCE)
        assistant.flush()
        await pilot.pause()

        # 原始源码是流式拼接的唯一真相，也是 markdown 渲染的输入。
        assert assistant.body_text == MARKDOWN_SOURCE

        body = assistant.query_one(".body")
        strips = widget_lines(body, body.size.width, body.size.height)
        rendered = "\n".join("".join(segment.text for segment in line) for line in strips)

        assert "```" not in rendered, f"围栏漏进了界面：\n{rendered}"
        assert "def f():" in rendered, rendered
        assert "**" not in rendered, rendered


async def check_spinner_lifecycle() -> None:
    app = make_app(tools=[])
    async with app.run_test(size=(80, 24)) as pilot:
        spinner = SpinnerLine()
        await app.query_one("#messages").mount(spinner)
        await pilot.pause()
        assert spinner.is_animating

        first = str(spinner.render())
        await pilot.pause(0.35)
        assert str(spinner.render()) != first, "spinner 帧没有推进"

        # 运行中被移除（取消、清屏）不能留下 interval。
        await spinner.remove()
        await pilot.pause()
        assert not spinner.is_animating


async def check_banner() -> None:
    wide = make_app(tools=[])
    async with wide.run_test(size=(110, 32)) as pilot:
        await pilot.pause()
        text = str(wide.query_one(".welcome").render())
        assert "Tau v" in text and "█" in text, text
        assert "fake · fake" in text, text

    narrow = make_app(tools=[])
    async with narrow.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        text = str(narrow.query_one(".welcome").render())
        assert "Tau v" in text, text
        assert "█" not in text, f"窄终端应降级为纯文字横幅：{text}"


async def check_tool_success() -> None:
    app = make_app(tools=[EchoTool()])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.query_one("#prompt").text = "跑一下 echo"
        await pilot.press("enter")
        await pilot.pause()

        blocks = app.query(ToolCallBlock)
        assert len(blocks) == 1
        block = blocks.first()

        head = str(block.query_one(".tool-head .body").render())
        assert head == "echo(你好)", head

        result = str(block.query_one(".tool-result .body").render())
        assert result == "你好 … +2 行 (ctrl+o 展开)", result
        assert not block.has_class("tool-error")
        assert str(block.query_one(".result-mark").render()) == "⎿"

        # 第一轮只调工具没有文字，那条空助手消息必须隐藏。
        visible = [m for m in app.query(AssistantMessage) if m.display]
        assert len(visible) == 1, f"应只留一条有文字的助手消息，实际 {len(visible)}"

        hint = str(app.query_one("#hint").render())
        assert hint == HINT_IDLE, f"回合结束后应恢复快捷键提示：{hint}"


async def check_tool_error() -> None:
    # 不给 harness 注册 echo，execute_tool_call 会返回 is_error=True。
    app = make_app(tools=[])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.query_one("#prompt").text = "跑一下 echo"
        await pilot.press("enter")
        await pilot.pause()

        block = app.query(ToolCallBlock).first()
        assert block.has_class("tool-error")

        result = str(block.query_one(".tool-result .body").render())
        assert result.startswith("Error: 未知工具：echo"), result


async def check_tool_expand() -> None:
    """折叠态一行摘要，展开态给足行数，但再长仍然截断。"""
    app = make_app(tools=[EchoTool(MANY_LINES)])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.query_one("#prompt").text = "跑一下 echo"
        await pilot.press("enter")
        await pilot.pause()

        block = app.query(ToolCallBlock).first()
        collapsed = str(block.query_one(".tool-result .body").render())
        assert collapsed.startswith("第 1 行 … +59 行 (ctrl+o 展开)"), collapsed
        assert not block.is_expanded

        await pilot.press("ctrl+o")
        await pilot.pause()

        assert block.is_expanded
        expanded = str(block.query_one(".tool-result .body").render())
        assert expanded.startswith("第 1 行\n第 2 行"), expanded
        # 一个读整个文件的 read 能把对话流冲掉，所以展开也有上限。
        assert f"还有 {60 - EXPANDED_LINES} 行未显示" in expanded, expanded

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert not block.is_expanded
        assert str(block.query_one(".tool-result .body").render()) == collapsed


async def main() -> None:
    check_pure_helpers()
    check_markdown_layer()
    await check_assistant_markdown()
    await check_spinner_lifecycle()
    await check_banner()
    await check_tool_success()
    await check_tool_error()
    await check_tool_expand()
    print("TUI 渲染检查通过")


if __name__ == "__main__":
    asyncio.run(main())
