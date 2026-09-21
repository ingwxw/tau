"""检查中文输入法下的提示行布局，以及 Claude Code 风格布局的约束。

这是确定性的 Textual 检查。原生 macOS 输入法候选窗由终端绘制，无头运行器
无法复现；这里改为在窄/常规宽度下用 CJK 文本跑一遍，确认布局稳定。

输入法相关的断言来自 dev-notes/tui-ime.md，改动界面时不应放松。
"""

import asyncio
from pathlib import Path

from textual import events
from textual._xterm_parser import XTermParser
from textual.color import Color
from textual.css.query import NoMatches

from tau_agent.harness import AgentHarness
from tau_ai.fake import FakeProvider
from tau_coding.session import CodingSession
from tau_coding.tui.app import PromptInput, TauTuiApp
from tau_coding.tui.widgets import AssistantMessage, UserMessage

SIZES = ((20, 8), (40, 12), (110, 32))

#: Claude Code 风格布局里不存在的旧组件。
REMOVED_SELECTORS = ("#sidebar", "#topbar", "#workspace", "#main-pane", "Footer")

#: ``#prompt`` 的高度上限，也就是最多显示 10 行文字。
PROMPT_CAP = 10

#: ``#composer`` 的高度上限：10 行文字 + 上下两条横线。
COMPOSER_CAP = PROMPT_CAP + 2

#: 160 格宽（CJK 每字 2 格），在三种宽度下都必然折行。
WRAP_TEXT = "第一句。" * 20

#: 1200 格宽，在三种宽度下都必然超过 10 行从而顶到上限。
HUGE_TEXT = "中文" * 600

#: 模拟输入法的关联文本。总长 ``6n + 6``（每个汉字 6 字符，``\x1b[49;;`` 占 6，
#: 末尾 ``u`` 占 1）：4 个汉字 30 字符还够得着 Textual 的 32 字符搜索上限，
#: 第 5 个一到 36 字符就越线。取 12 个，跨过那条边界并留出余量。
ASSOCIATED_TEXT = "我怎么知道你要干什么呢嗯"


def make_session() -> CodingSession:
    harness = AgentHarness(
        provider=FakeProvider(),
        model="fake",
        system="test",
        tools=[],
    )
    return CodingSession(project_dir=Path.cwd(), harness=harness)


def check_ime_contract(app: TauTuiApp) -> None:
    """dev-notes/tui-ime.md 记录的约束，逐条钉住。"""
    prompt = app.query_one("#prompt", PromptInput)

    assert prompt.placeholder == ""
    assert prompt.styles.overflow_x == "hidden"
    # 纵向从 hidden 放宽成 auto 是「封顶后还能滚到看不见的部分」的前提；
    # 不画条子靠下面的 scrollbar-size 为 0。
    assert prompt.styles.overflow_y == "auto"
    assert prompt.scrollbar_size_horizontal == 0
    assert prompt.scrollbar_size_vertical == 0

    # 必须与主界面**同底色**：输入法在硬件光标处绘制预编辑串，实色背景会把
    # 这一行误显示成第二条输入行。断言的是「和 Screen 一样」而不是某个具体
    # 色值——早先这里写死 r/g/b == 0，只是当时底色恰好是纯黑；底色一改，
    # 它会以「输入法约束被破坏」的样子报错，而真正被破坏的其实只是这个断言。
    assert prompt.styles.background == app.screen.styles.background, (
        f"输入行底色 {prompt.styles.background} 和主界面 "
        f"{app.screen.styles.background} 不一致，会显出一条带子"
    )
    assert prompt.styles.background_tint.a == 0

    # 上面查的只是组件级底色，真正会往输入行上铺带子的是这几个开关。
    # highlight_cursor_line 只能在构造时给，运行中赋值过不了 _line_cache。
    assert prompt.highlight_cursor_line is False
    assert prompt.soft_wrap is True
    # 一旦变成 "indent"，TextArea 会把 escape 一起吞掉，App 的取消就没了。
    assert prompt.tab_behavior == "focus"

    # 括号底色是 reactive(init=False) 且没有 watcher，关不掉，只能靠 CSS。
    # 断言「与编辑区同色」而不是「透明」：要防的是有一条看得见的带子，
    # 至于它到底是什么颜色不重要。默认值在这里会解成灰色。
    bracket = prompt.get_component_rich_style("text-area--matching-bracket")
    assert Color.from_rich_color(bracket.bgcolor) == prompt.styles.background, (
        f"括号底色和输入行底色不一致，会显出一条带子：{bracket.bgcolor!r}"
    )


async def check_ime_associated_text(app: TauTuiApp, pilot) -> None:
    """输入法的关联文本不能被当成字面乱码打进提示框。

    kitty 键盘协议的关联文本报告形如 ``CSI 49;;<码点表>u``，Textual 也实现了
    它的解析（取第三个分号段当字符）。问题在解析之前那道
    ``_MAX_SEQUENCE_SEARCH_THRESHOLD = 32`` 的闸门：组合串一旦超过 32 字符就整个
    放弃，改成把原始字节逐字重发成按键（ESC 变成 ``^``），于是长一点的中文会
    变成 ``^[49;;25105:24590:...u`` 打进输入框。
    ``kitty_text.widen_sequence_search`` 抬高了这道闸门，这里钉住效果。

    断言的是**解出来的字符**而不是那个上限常量：上游哪天自己修好、把常量删掉，
    这条检查照样应该通过。调用前需先构造过 ``TauTuiApp``（补丁在它的
    ``__init__`` 里打上）。
    """
    payload = (
        "\x1b[49;;"
        + ":".join(str(ord(char)) for char in ASSOCIATED_TEXT)
        + "u"
    )
    keys = [
        event
        for event in XTermParser().feed(payload)
        if isinstance(event, events.Key)
    ]
    typed = "".join(event.character or "" for event in keys)
    assert typed == ASSOCIATED_TEXT, (
        f"长组合串被当成字面按键塞进来了：{typed!r}"
    )

    # 解析对了不等于落进输入框是对的，再把同样的按键喂给控件走一遍。
    prompt = app.query_one("#prompt", PromptInput)
    for event in keys:
        await prompt._on_key(event)
    await pilot.pause()
    assert prompt.text == ASSOCIATED_TEXT, (
        f"组合文本落进输入框变成了：{prompt.text!r}"
    )

    prompt.text = ""
    await pilot.pause()


def check_layout_contract(app: TauTuiApp) -> None:
    for selector in REMOVED_SELECTORS:
        try:
            app.query_one(selector)
        except NoMatches:
            continue
        raise AssertionError(f"{selector} 不应存在于单栏对话流布局中")

    # 空输入时仍然是「上横线 1 + 内容 1 + 下横线 1」。
    assert app.query_one("#composer").region.height == 3
    assert app.query_one("#prompt").region.height == 1
    assert app.query_one("#prompt-row").region.height == 1
    assert app.query_one("#hint").region.height == 1
    assert app.query_one("#messages").region.height > 0


async def check_marked_rows(app: TauTuiApp, pilot) -> None:
    """标记列与正文列分离，折行续行才对得齐。"""
    messages = app.query_one("#messages")

    user = UserMessage("读取 session.py")
    await messages.mount(user)
    assistant = AssistantMessage()
    await messages.mount(assistant)
    assistant.append_text("这个文件定义了 CodingSession。")
    await pilot.pause()

    # 字形取自 Claude Code 的用户行首（U+276F）。
    assert str(user.query_one(".mark").render()) == "❯"
    assert str(assistant.query_one(".mark").render()) == "⏺"

    # 角色 class 是配色选择器的唯一锚点，漏挂会让 > 和 ⏺ 同色。
    assert user.has_class("user-message")
    assert assistant.has_class("assistant-message")

    user_mark = user.query_one(".mark").region
    user_body = user.query_one(".body").region
    assert user_body.x > user_mark.x
    assert user_body.width > user_mark.width


async def check_soft_wrap(app: TauTuiApp, pilot, *, height: int) -> None:
    """软换行：框跟着文字长，封顶后不再长，清空后缩回去。

    这里钉的是「折行是软的」——文字里不该出现 ``\\n``，长高完全由
    ``TextArea`` 的 ``virtual_size`` 驱动。
    """
    prompt = app.query_one("#prompt", PromptInput)
    composer = app.query_one("#composer")

    prompt.text = WRAP_TEXT
    await pilot.pause()
    assert "\n" not in prompt.text, "折行不该往文本里插换行"
    assert prompt.region.height > 1, f"长文本没有折行：高 {prompt.region.height}"
    assert composer.region.height > 3, (
        f"输入框没有跟着长高：{composer.region.height}"
    )
    assert composer.region.height <= COMPOSER_CAP

    prompt.text = HUGE_TEXT
    await pilot.pause()
    assert prompt.region.height <= PROMPT_CAP, (
        f"超过 {PROMPT_CAP} 行还没封顶：{prompt.region.height}"
    )
    assert composer.region.height <= COMPOSER_CAP, (
        f"输入框超过 {COMPOSER_CAP} 行还没封顶：{composer.region.height}"
    )
    # 终端够高时，才谈得上「真的顶到了上限」而不是被屏幕挤扁。
    if height >= COMPOSER_CAP + 2:
        assert composer.region.height == COMPOSER_CAP, (
            f"顶不到上限：{composer.region.height}"
        )

    # 封顶之后光标必须还在可视区内。这条最容易漏：上限如果封在容器上而不是
    # #prompt 上，容器会把整个 43 行高的 TextArea 裁掉，而 TextArea 自认为
    # 完全可见、根本不滚——光标跑出框外就再也看不见了，打字全靠盲打。
    prompt.move_cursor(prompt.document.end)
    await pilot.pause()
    caret = prompt.cursor_screen_offset
    assert prompt.region.y <= caret.y < prompt.region.y + prompt.region.height, (
        f"光标跑到输入框外了：光标 y={caret.y}，"
        f"输入框 y={prompt.region.y} 高 {prompt.region.height}"
    )
    assert prompt.scroll_offset.y > 0, "封顶之后没有滚动，光标是跟不住的"

    prompt.text = ""
    await pilot.pause()
    assert composer.region.height == 3, (
        f"清空后没缩回去：{composer.region.height}"
    )
    assert prompt.region.height == 1


async def check_ctrl_x_keeps_draft(app: TauTuiApp, pilot) -> None:
    """``ctrl+x`` 不能吃掉正在写的草稿。

    ``TextArea.action_cut`` 在无选区时会删掉整行，而 ``ctrl+x`` 在本应用里
    是「中断」。这个覆写很容易被后来的人当成多余代码删掉，所以两头都钉：
    没选中时不动文本，真选中了仍然要能剪切。
    """
    prompt = app.query_one("#prompt", PromptInput)
    draft = "别把我删了"

    prompt.text = draft
    await pilot.pause()
    await pilot.press("ctrl+x")
    await pilot.pause()
    assert prompt.text == draft, "没选中内容时 ctrl+x 不该动草稿"

    # 反过来：真选中了还是得能切，否则这个覆写就成了「cut 永久失效」。
    await pilot.press("end")
    await pilot.press("shift+home")
    await pilot.pause()
    await pilot.press("ctrl+x")
    await pilot.pause()
    assert prompt.text == "", "选中内容后 ctrl+x 应该把它切走"


async def main() -> None:
    for width, height in SIZES:
        app = TauTuiApp(make_session(), provider_name="fake", model="fake")
        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause()

            check_ime_contract(app)
            check_layout_contract(app)
            await check_ime_associated_text(app, pilot)
            await check_marked_rows(app, pilot)
            await check_soft_wrap(app, pilot, height=height)
            await check_ctrl_x_keeps_draft(app, pilot)

    print("TUI 中文输入布局检查通过")


if __name__ == "__main__":
    asyncio.run(main())
