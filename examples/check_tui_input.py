"""输入区交互：命令面板、忙碌排队、ctrl+c 双按退出、未读跟随。

这里钉的都是「按下去没反应但也不报错」的情况：面板要靠 ``TextArea.Changed``
才会弹，队列要在同一个 worker 里抽干，``ctrl+c`` 得绕开 ``TextArea`` 的复制
绑定。任何一处接错线，界面照样跑，只是那几个键静默失效。

最重要的不变式在最前面：**忙碌时焦点必须留在 ``#prompt`` 上**。macOS 输入法
把预编辑串画在硬件光标处，一旦失焦就不能打字了——这条比排队功能本身重要。
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
from tau_ai.fake import FakeProvider
from tau_coding.session import CodingSession
from tau_coding.tui.app import QUIT_CONFIRM_WINDOW, TauTuiApp
from tau_coding.tui.widgets import (
    HINT_IDLE,
    CommandPalette,
    MessageList,
    PromptInput,
    UserMessage,
)

#: 一条用户消息，用在需要滚动历史的检查里。
LONG_TEXT = "第一句。" * 20


class SlowProvider:
    """慢慢吐字的 provider，好让测试在回合中途插进输入或取消。

    ``gap`` 是字与字之间的间隔。取消是**协作式**的（``loop.run_agent_loop``
    只在事件之间查一次 token），所以测试必须让它有醒来查看的机会：先 ``sleep``
    一段再吐字的 provider 会让 ``ctrl+c`` 看起来像失灵，实际是循环压根没回到
    判断点。真实 provider 每收到一个 chunk 就回一次循环，``gap`` 才是它的形状。
    """

    def __init__(self, *, delay: float = 0.4, text: str = "好", gap: float = 0.0) -> None:
        self._delay = delay
        self._text = text
        self._gap = gap

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
            if self._gap:
                await asyncio.sleep(self._gap)
        yield AssistantDoneEvent(AssistantMessage([TextContent(self._text)]))


def make_app(*, provider: object = None) -> TauTuiApp:
    harness = AgentHarness(
        provider=provider or FakeProvider(),  # type: ignore[arg-type]
        model="fake",
        system="test",
        tools=[],
    )
    return TauTuiApp(
        CodingSession(project_dir=Path.cwd(), harness=harness),
        provider_name="fake",
        model="fake",
    )


def hint(app: TauTuiApp) -> str:
    return str(app.query_one("#hint").render())


async def send(app: TauTuiApp, pilot, content: str) -> None:
    app.query_one("#prompt", PromptInput).text = content
    await pilot.press("enter")


async def check_palette() -> None:
    """输入 / 弹命令面板；上下键选择、tab 补全、enter 直接执行。"""
    app = make_app()
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        palette = app.query_one(CommandPalette)
        prompt = app.query_one("#prompt", PromptInput)
        assert not palette.is_open

        # 普通输入不弹。
        prompt.text = "你好"
        await pilot.pause()
        assert not palette.is_open, "普通输入不该弹命令面板"

        prompt.text = "/"
        await pilot.pause()
        assert palette.is_open, "输入 / 之后面板没弹出来（Changed 没接上？）"
        listed = str(palette.render())
        for name in ("/clear", "/cancel", "/quit"):
            assert name in listed, f"{name} 没出现在面板里：{listed}"

        # 前缀过滤。
        prompt.text = "/c"
        await pilot.pause()
        listed = str(palette.render())
        assert "/clear" in listed and "/cancel" in listed, listed
        assert "/quit" not in listed, f"面板没有按前缀过滤：{listed}"

        # 上下键选择，tab 补全但不发送。
        await pilot.press("down")
        await pilot.press("tab")
        await pilot.pause()
        assert prompt.text == "/cancel", f"tab 没补全选中的命令：{prompt.text!r}"
        assert not app.query(UserMessage), "tab 只是补全，不该发送"
        assert not palette.is_open, "补全成唯一匹配后面板该自己收起"

        # 打全了就不再挡着输入框。
        prompt.text = "/clear"
        await pilot.pause()
        assert not palette.is_open, "已经打全的命令不该继续弹面板"

        # escape 关面板，但不能吃掉已经输入的内容。
        prompt.text = "/q"
        await pilot.pause()
        assert palette.is_open
        await pilot.press("escape")
        await pilot.pause()
        assert not palette.is_open, "escape 没关掉面板"
        assert prompt.text == "/q", f"escape 关面板时吃掉了输入：{prompt.text!r}"

        # 面板开着时回车是「执行选中的命令」，不是发送框里的半截文字。
        prompt.text = "/"
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert not app.query(UserMessage), "命令不该被当成聊天内容发出去"


async def check_busy_queue() -> None:
    """忙碌时输入框照常可用，提交的内容排队而不是被拒。"""
    app = make_app(provider=SlowProvider(delay=0.4))
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        await send(app, pilot, "第一条")
        await pilot.pause(0.1)

        assert app.is_busy
        prompt = app.query_one("#prompt", PromptInput)
        # 输入法的硬约束：忙碌时也不能 disable / 失焦，否则中文就打不进去。
        assert not prompt.disabled, "忙碌时输入框不能 disable"
        assert app.focused is prompt, "忙碌时焦点必须仍在 #prompt 上"

        await send(app, pilot, "第二条")
        await pilot.pause()
        assert "已排队 1 条" in hint(app), hint(app)

        await pilot.pause(1.6)
        texts = [message.body_text for message in app.query(UserMessage)]
        assert texts == ["第一条", "第二条"], f"排队的内容没按顺序发出：{texts}"
        assert not app.is_busy
        assert hint(app) == HINT_IDLE, hint(app)


async def check_busy_timer() -> None:
    """忙碌提示行给出本回合跑了多久，而且是**真的在走**。

    只断言出现「已运行」不够：写死成 ``已运行 0s`` 也能过，而那正是这个功能
    失效时的样子。所以隔一秒再取一次，要求字符串变过。
    """
    app = make_app(provider=SlowProvider(delay=0.0, text="字" * 60, gap=0.05))
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        await send(app, pilot, "跑一会儿")
        await pilot.pause(0.2)

        first = hint(app)
        assert "已运行" in first, f"忙碌时没给出计时：{first}"
        assert first != HINT_IDLE, first

        await pilot.pause(1.2)
        second = hint(app)
        assert second != first, f"计时没有推进：{first} → {second}"

        # 收尾：把回合取消掉，别让 worker 活过 run_test 的退出。
        await pilot.press("ctrl+c")
        await pilot.pause(0.3)


async def check_ctrl_c() -> None:
    """ctrl+c：有草稿先清草稿，空输入连按两次才退出。"""
    app = make_app(provider=SlowProvider(delay=5.0))
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptInput)
        assert app.is_running

        # 有草稿：清掉，但不退出。
        prompt.text = "别退出"
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert prompt.text == "", f"ctrl+c 应该先清空草稿：{prompt.text!r}"
        assert app.is_running, "第一次 ctrl+c 不该退出"

        # 输入框空着：第一次只是警告。
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running, "空输入时第一次 ctrl+c 不该退出"
        assert "再按一次" in hint(app), hint(app)

        # 第二次才真的退。
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app.is_running, "连按两次 ctrl+c 应该退出"


async def check_ctrl_c_cancels_turn() -> None:
    """忙碌时 ctrl+c 是中断，不是退出。"""
    app = make_app(provider=SlowProvider(delay=0.0, text="字" * 200, gap=0.05))
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        await send(app, pilot, "跑个很久的东西")
        await pilot.pause(0.3)
        assert app.is_busy

        await pilot.press("ctrl+c")
        await pilot.pause(0.3)
        assert app.is_running, "忙碌时 ctrl+c 只该中断，不该退出"
        assert not app.is_busy, "ctrl+c 没有中断当前回合"


async def check_ctrl_c_keeps_selection_copy() -> None:
    """输入框里有选区时 ctrl+c 是复制，不能被退出绑定抢走。"""
    app = make_app()
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptInput)
        prompt.text = "复制我"
        prompt.selection = ((0, 0), (0, 3))
        await pilot.pause()

        await pilot.press("ctrl+c")
        await pilot.pause()
        # 关键不是剪贴板里有什么（无头环境里没有剪贴板），而是这一下
        # 既没有退出也没有清空草稿——它整个交给了 TextArea。
        assert app.is_running, "有选区时 ctrl+c 不该触发退出流程"
        assert prompt.text == "复制我", f"有选区时 ctrl+c 不该动文本：{prompt.text!r}"


async def check_unread_and_follow() -> None:
    """滚上去就不再跟随，提示行给出未读行数；escape 回到底部并清零。

    内容必须走真实路径进去（提交输入 → 回合产出 → ``_after_content``）：
    ``follow`` 记的是「用户停没停在底部」这个意图，而维持它的正是
    ``_after_content`` 里的 ``scroll_end``。直接往 ``#messages`` 上 mount
    会造出一个界面上不存在、也没人去滚动的中间态。
    """
    app = make_app(provider=SlowProvider(delay=0.0, text=LONG_TEXT))
    async with app.run_test(size=(60, 12)) as pilot:
        await pilot.pause()
        messages = app.query_one("#messages", MessageList)

        for index in range(4):
            await send(app, pilot, f"第 {index} 条")
            await pilot.pause(0.15)

        assert messages.follow, "新会话默认应该跟住底部"
        assert messages.max_scroll_y > 0, "内容没撑满，这条检查没有意义"

        messages.scroll_up(animate=False)
        await pilot.pause()
        assert not messages.follow, "往上滚之后不该继续跟随"
        unread = hint(app)
        assert "还有" in unread and "行" in unread, f"没有给出未读行数：{unread}"

        # 跟随停住之后，新内容不能再把视图拽回底部。
        offset = messages.scroll_offset.y
        await send(app, pilot, "打断跟随的一条")
        await pilot.pause(0.2)
        assert messages.scroll_offset.y == offset, "停止跟随后视图仍被拽走了"

        # escape 是「回到最新」。
        await pilot.press("escape")
        await pilot.pause()
        assert messages.follow, "escape 没有回到底部"
        assert hint(app) == HINT_IDLE, f"回到最新后未读没有清零：{hint(app)}"


async def main() -> None:
    await check_palette()
    await check_busy_queue()
    await check_busy_timer()
    await check_ctrl_c()
    await check_ctrl_c_cancels_turn()
    await check_ctrl_c_keeps_selection_copy()
    await check_unread_and_follow()
    print("TUI 输入交互检查通过")


if __name__ == "__main__":
    assert QUIT_CONFIRM_WINDOW > 0
    asyncio.run(main())
