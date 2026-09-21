"""框选与复制：助手正文选得中、ctrl+c 复制得走、宽度变了还对得上。

这里钉的三条都是**不看这个检查就发现不了**的：界面照样跑、正文照样显示，
只是鼠标拖过去什么都没有。

1. **助手正文必须是可选的。** 它一度是 Rich ``Markdown`` 对象，而
   ``visualize()`` 会把任何 Rich 对象包成 ``RichVisual``——``RichVisual``
   直接 ``Strip(line)`` 包装，不带 ``style._meta["offset"]``。合成器靠这个
   meta 找到内容控件，找不到就退化成容器级选区，于是拖拽选中一片空白。
   用户消息（纯文本 ``Text``）一直是好的，所以这个 bug 只藏在助手回复里。
2. **``ctrl+c`` 得让位给复制。** App 上那条 ``interrupt`` 是 priority 绑定，
   会遮蔽 ``Screen`` 的 ``ctrl+c,super+c``。让位只能靠 ``check_action`` 返回
   假——但**只能在真有选区时让**：``Screen.action_copy_text`` 在无选区时
   ``raise SkipAction()``，无条件让位会让空选区下的 ``ctrl+c`` 一路跳过，
   连退出都一起废掉（第 4 条检查盯的就是这个）。
3. **渲染行数必须等于控件高度。** Markdown 按宽度预渲染，高度和内容一旦出自
   不同的宽度，多出来的行不会报错，只是被 ``overflow: hidden`` 裁掉——正文
   看起来"就一行"。第 2 条检查在两种宽度下都比对这两个数。
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from textual.content import Content

from tau_agent.harness import AgentHarness
from tau_agent.messages import AgentMessage, AssistantMessage, TextContent
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_coding.session import CodingSession
from tau_coding.tui.app import TauTuiApp
from tau_coding.tui.theme import SUBTLE
from tau_coding.tui.widgets import AssistantMessage as AssistantRow
from tau_coding.tui.widgets import PromptInput

#: 一段长正文，窄下来必须折行；标题放在最前面，方便按行定位。
SOURCE = (
    "# 一级标题\n"
    "\n"
    "正文一句话。" * 1
    + "这句话要够长，长到窄终端里不得不折成好几行，"
    "否则「高度跟着宽度走」这条根本没有观察对象。\n"
    "\n"
    "- 列表甲\n"
    "- 列表乙\n"
)

#: 正文第一行渲染出来的样子（Rich 会把 ``#`` 吃掉）。
FIRST_LINE = "一级标题"


class MarkdownProvider:
    """一次性吐出整段 Markdown，好让检查拿到稳定的渲染结果。"""

    async def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[object],
    ) -> AsyncGenerator[AssistantMessageEvent, None]:
        yield AssistantStartEvent()
        yield TextDeltaEvent(SOURCE)
        yield AssistantDoneEvent(AssistantMessage([TextContent(SOURCE)]))


def make_app() -> TauTuiApp:
    harness = AgentHarness(
        provider=MarkdownProvider(),  # type: ignore[arg-type]
        model="fake",
        system="test",
        tools=[],
    )
    return TauTuiApp(
        CodingSession(project_dir=Path.cwd(), harness=harness),
        provider_name="fake",
        model="fake",
    )


async def ask(app: TauTuiApp, pilot) -> AssistantRow:
    """发一句话，等回合并拿到助手那一行。"""
    app.query_one("#prompt", PromptInput).text = "画点东西"
    await pilot.press("enter")
    await pilot.pause(0.2)
    rows = [row for row in app.query(AssistantRow) if row.display]
    assert rows, "没有助手消息行"
    return rows[-1]


def body_of(row: AssistantRow):
    return row.query_one(".body")


async def drag(pilot, x: int, y: int, to_x: int) -> str:
    """在屏幕坐标上从 ``(x, y)`` 拖到 ``(to_x, y)``，返回选中的文本。"""
    await pilot.mouse_down(offset=(x, y))
    await pilot.hover(offset=(to_x, y))
    await pilot.mouse_up(offset=(to_x, y))
    await pilot.pause()
    return pilot.app.screen.get_selected_text() or ""


def assert_height_matches_render(row: AssistantRow) -> None:
    """控件高度必须等于渲染出来的行数。

    这两个数一旦不一致，多出来的行不会报错，只是被裁掉——正文显示成一行，
    而内容其实渲染好了。所以比对的是「渲染结果的行数」而不是
    ``get_content_height``：后者和控件高度是同一个来源，比了等于没比。
    """
    body = body_of(row)
    content = body.render()
    lines = content.plain.split("\n")
    assert body.region.height == len(lines), (
        f"控件高 {body.region.height} 行，渲染出来却有 {len(lines)} 行——"
        f"多出来的被裁掉了。宽度 {body.content_size.width}，"
        f"缓存里那一版是宽度 {body._rendered[0] if body._rendered else None}"
    )


async def check_body_is_selectable() -> None:
    """鼠标拖过助手正文要真的选中文字，而不是选中一片空白。"""
    app = make_app()
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        row = await ask(app, pilot)
        body = body_of(row)

        # 出口必须是 Content。Rich 对象会被包成 RichVisual，那条路选不中。
        assert isinstance(body.render(), Content), (
            f"正文渲染成了 {type(body.render()).__name__}，"
            "只有 Content 能被框选（Rich 对象会走 RichVisual，选区锚不上）"
        )
        assert_height_matches_render(row)

        region = body.region
        picked = await drag(pilot, region.x, region.y, region.x + 6)
        assert picked, "拖过助手正文什么都没选中"
        assert FIRST_LINE.startswith(picked) or picked.startswith(FIRST_LINE[:2]), (
            f"选中的内容和正文对不上：{picked!r}"
        )

        # 第二条：连列表项也要能选——它是缩进过的，过去整块都取不到。
        app.screen.clear_selection()
        await pilot.pause()
        middle = region.y + 2
        assert await drag(pilot, region.x, middle, region.x + 8), (
            "正文中间那几行选不中"
        )


async def check_width_change_keeps_lines_honest() -> None:
    """宽度变了要重排：渲染行数和控件高度都得跟着走。"""
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        row = await ask(app, pilot)
        body = body_of(row)
        assert_height_matches_render(row)
        wide = len(body.render().plain.split("\n"))

        await pilot.resize_terminal(52, 30)
        await pilot.pause()
        assert_height_matches_render(row)
        narrow = len(body.render().plain.split("\n"))
        assert narrow > wide, (
            f"窄下来没有重排：{wide} 行 → {narrow} 行。"
            "渲染结果还停在旧宽度上，超过宽度的部分会被裁掉"
        )

        # 重排之后选区也得跟着对上，否则选中的是旧宽度下的字符位置。
        region = body.region
        assert await drag(pilot, region.x, region.y, region.x + 6), (
            "改宽度之后正文选不中了"
        )


async def check_ctrl_c_copies_instead_of_quitting() -> None:
    """有选区时 ctrl+c 是复制：不退出、不中断、不动草稿。"""
    app = make_app()
    copied: list[str] = []
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        app.copy_to_clipboard = lambda text="", **kw: copied.append(text)  # type: ignore[method-assign]

        row = await ask(app, pilot)
        # 草稿必须在拖拽**之前**设。``TextArea`` 的选区一变就会
        # ``app.clear_selection()``（Textual 的设计：动了输入框就不再是
        # 「选中屏幕上的东西」那个语境），设晚了会把刚拖出来的选区清掉，
        # 于是 ctrl+c 走回中断分支——那是检查自己造出来的假象。
        app.query_one("#prompt", PromptInput).text = "别动我的草稿"
        await pilot.pause()

        region = body_of(row).region
        picked = await drag(pilot, region.x, region.y, region.x + 6)
        assert picked, "拖拽没选中，这条检查没有意义"

        await pilot.press("ctrl+c")
        await pilot.pause()

        assert copied == [picked], f"ctrl+c 没有复制选中的文本：{copied!r}"
        assert app.is_running, "有选区时 ctrl+c 不该走退出流程"
        assert app.query_one("#prompt", PromptInput).text == "别动我的草稿", (
            "有选区时 ctrl+c 不该动草稿"
        )


async def check_ctrl_c_without_selection_still_quits() -> None:
    """没有选区时 ctrl+c 的行为一个字都不能变。

    这是第 2 条检查的反面：``check_action`` 里若把 ``interrupt`` 无条件让给
    ``Screen.action_copy_text``，空选区下它会 ``raise SkipAction()`` 然后一路
    跳过，第二次 ``ctrl+c`` 再也退不出去——而且不报任何错。
    """
    app = make_app()
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptInput)
        assert app.screen.get_selected_text() is None, "这条检查要求一开始没有选区"

        prompt.text = "别退出"
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert prompt.text == "", f"ctrl+c 应该先清空草稿：{prompt.text!r}"
        assert app.is_running, "第一次 ctrl+c 不该退出"

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running, "空输入时第一次 ctrl+c 不该退出"
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app.is_running, "连按两次 ctrl+c 应该退出"


async def check_selection_colour() -> None:
    """选区配色：中性灰，且不覆盖正文颜色。

    默认是主题的亮蓝，在纯黑上很扎眼。``color: transparent`` 是关键——换成
    具体颜色会把选区里的语法色整片刷掉。
    """
    app = make_app()
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        styles = app.screen.get_component_styles("screen--selection")
        assert styles.background.hex == SUBTLE.upper(), (
            f"选区底色 {styles.background.hex}，应该是 $tau-subtle"
        )
        assert styles.color.a == 0, (
            f"选区前景色不是 transparent（{styles.color}），会把正文颜色刷掉"
        )


async def main() -> None:
    await check_body_is_selectable()
    await check_width_change_keeps_lines_honest()
    await check_ctrl_c_copies_instead_of_quitting()
    await check_ctrl_c_without_selection_still_quits()
    await check_selection_colour()
    print("TUI 框选与复制检查通过")


if __name__ == "__main__":
    asyncio.run(main())
