"""Tau 的 Textual 前端，界面语言对齐 Claude Code。

布局是一列到底的对话流：引导横幅、消息、spinner，底部双横线输入框加一行灰色提示。
没有侧边栏也没有顶栏——workspace / provider / model 都收进横幅，快捷键收进提示行。

几条不显然的约定：

- **输入框永远保持焦点。** 忙碌时也不 disable、不 blur，因为 macOS 输入法的
  预编辑串画在硬件光标处，焦点一跑输入法就废了。代价是 `ctrl+x` / `ctrl+c`
  这类快捷键会被 ``TextArea`` 先接住，只能由 ``PromptInput`` 转交回来。
- **命令面板不用 ``OptionList``。** 同上，它可聚焦，会把光标从输入框抢走。
  选中项由 App 维护，面板只负责画。
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from time import monotonic
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static, TextArea

from tau_agent.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_coding.session import CodingSession
from tau_coding.tui.kitty_text import widen_sequence_search
from tau_coding.tui.theme import ERROR, INACTIVE, PALETTE
from tau_coding.tui.widgets import (
    HINT_IDLE,
    AssistantMessage,
    Command,
    CommandPalette,
    Composer,
    HintLine,
    MessageList,
    PromptInput,
    SpinnerLine,
    ToolCallBlock,
    UserMessage,
    WelcomeBanner,
)

#: ctrl+c 需要在这个秒数内按第二次才真的退出。
QUIT_CONFIRM_WINDOW = 2.0

__all__ = ["HINT_IDLE", "PromptInput", "TauTuiApp"]


class TauTuiApp(App[None]):
    TITLE = "Tau"
    SUB_TITLE = "Coding Agent"

    CSS = """
    Screen {
        background: $tau-bg;
        color: $tau-text;
    }

    #messages {
        height: 1fr;
        padding: 0 2;
        background: $tau-bg;
        /* 不画滚动条，对齐 Claude Code。条宽为 0 同时也断掉了「滚动条出现 →
           折行宽度变化 → 重新折行」这个回环。「上面还有内容」的线索由提示行的
           未读计数承担（HintLine.set_unread）。 */
        scrollbar-size-vertical: 0;
    }

    /* 选区。默认取主题的 $screen-selection-background（亮蓝），在纯黑上很扎眼；
       换成中性灰，和 $tau-subtle 的边框、分隔线是同一档。
       `color: transparent` 才是关键：默认主题本来就是 transparent，这里显式钉住，
       免得换个主题就把选区里的语法色全刷成单色。 */
    Screen > .screen--selection {
        background: $tau-subtle;
        color: transparent;
    }

    .welcome {
        height: auto;
        margin: 1 0;
    }

    /* 消息行：定宽标记列 + 正文列。正文列 1fr 让折行续行对齐到正文，
       而不是回到标记下面。 */
    .mark {
        width: 2;
        height: 1;
    }

    .body {
        width: 1fr;
        height: auto;
        text-wrap: wrap;
    }

    .user-message {
        height: auto;
        margin-bottom: 1;
    }

    /* 用户行首的 ❯ 用 subtle：Claude Code 的转写区提示符就是这个色，
       比助手的 ⏺（正文色）暗一档，一眼能分出谁说的。 */
    .user-message .mark {
        color: $tau-subtle;
    }

    .assistant-message {
        height: auto;
        margin-bottom: 1;
    }

    .assistant-message .mark {
        color: $tau-text;
    }

    .tool-block {
        height: auto;
        margin-bottom: 1;
    }

    .tool-head .mark {
        color: $tau-text;
    }

    /* ⎿ 比 ⏺ 再缩进两格，结果行因此落在工具名下方的层级上。 */
    .tool-result {
        height: auto;
        margin-left: 2;
    }

    .result-mark {
        width: 3;
        height: 1;
        color: $tau-inactive;
    }

    .tool-result .body {
        color: $tau-inactive;
    }

    .tool-block.tool-error .tool-head .body {
        color: $tau-error;
    }

    .tool-block.tool-error .result-mark {
        color: $tau-error;
    }

    .spinner {
        height: 1;
        margin-bottom: 1;
    }

    #dock {
        height: auto;
        padding: 0 2 0 0;
        background: $tau-bg;
    }

    /*
     * 命令面板：输入 / 时浮在输入框上方，高度跟着候选条数走。
     * 左内边距 3 是让命令行和输入框里的正文列对齐（dock 0 + composer 1 +
     * 提示符列 2）。
     */
    #palette {
        height: auto;
        max-height: 8;
        padding: 0 1 0 3;
        background: $tau-bg;
        color: $tau-inactive;
    }

    /*
     * 高度不写死：上横线 1 + 最多 10 行文字 + 下横线 1。
     * 上限必须封在 #prompt 上而不是这里——封在容器上只会把 #prompt 连内容
     * 一起裁掉（它照样是 43 行高，于是自认为完全可见、根本不滚），光标跑出
     * 可视区就找不回来了。封在 #prompt 上它才会自己滚。
     */
    #composer {
        height: auto;
        padding: 0 1;
        border-top: solid $tau-prompt-border;
        border-bottom: solid $tau-prompt-border;
        background: $tau-bg;
    }

    #prompt-row {
        height: auto;
    }

    #prompt-prefix {
        width: 2;
        height: 1;
        /* 和转写区的 ❯ 同色，输入行和它上面那行看着是一回事。 */
        color: $tau-subtle;
    }

    #prompt {
        /* 10 行文字封顶。封顶后它才会成为滚动主体，光标始终留在可视区内。 */
        height: auto;
        max-height: 10;
        width: 1fr;
        /*
         * 编辑区与终端同底色。macOS 输入法在硬件光标处绘制预编辑串，
         * 实色背景或聚焦 tint 会把这一行误显示成第二条输入行。
         */
        background: $tau-bg;
        background-tint: $tau-bg 0%;
        color: $tau-text;
        border: none;
        padding: 0;
        overflow-x: hidden;
        /*
         * 纵向必须能滚，否则封顶之后看不见的部分就真没了（hidden 会让
         * Textual 直接把垂直滚动判成不可用）。但不画滚动条：灰色的滚动区
         * 会和预编辑串叠在一起。条宽为 0 同时也断掉了「滚动条出现 → 折行
         * 宽度变化 → 重新折行」这个回环。
         */
        overflow-y: auto;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 0;
    }

    #prompt:focus {
        background: $tau-bg;
        background-tint: $tau-bg 0%;
    }

    /*
     * 光标落在括号上时默认会铺一层底色，也是一条实色带子。这个开关是
     * reactive(init=False) 且没有 watcher，构造后赋值同样过不了 _line_cache，
     * 只能在 CSS 里关。
     */
    #prompt .text-area--matching-bracket {
        background: transparent;
    }

    /*
     * 光标那一格的底色取自主题的 $input-cursor-background（深色主题下接近
     * 纯白），没有开关可关。钉成一个明确的块状光标，免得换主题时突然变成
     * 一条刺眼的白色带子。
     */
    #prompt .text-area--cursor {
        background: $tau-text;
        color: $tau-bg;
    }

    #hint {
        height: 1;
        margin-left: 2;
        color: $tau-inactive;
        /* 窄终端下别从中间硬切，「ctrl+q 退出」被切掉比省略号更难看出少了东西。 */
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+x", "cancel", "中断"),
        ("escape", "cancel", "中断"),
        Binding("ctrl+c", "interrupt", "中断/退出", show=False, priority=True),
        ("ctrl+o", "toggle_tools", "展开结果"),
        ("ctrl+l", "clear", "清屏"),
        ("ctrl+q", "request_quit", "退出"),
        # 面板打开时上下键选命令、tab 补全。非 priority 的绑定到不了这里：
        # 焦点在 TextArea 上，上下键会被它当成光标移动先吃掉。
        Binding("up", "palette_move(-1)", "上一条", show=False, priority=True),
        Binding("down", "palette_move(1)", "下一条", show=False, priority=True),
        Binding("tab", "palette_accept", "补全", show=False, priority=True),
    ]

    def __init__(
        self,
        session: CodingSession,
        *,
        provider_name: str = "provider",
        model: str = "unknown",
    ) -> None:
        # 必须在 run() 之前打上：驱动线程一起来就会开始解析终端输入，
        # 而输入法组合串能不能被解出来取决于这道补丁。见 kitty_text。
        widen_sequence_search()
        super().__init__()
        self._session = session
        self._provider_name = provider_name
        self._model = model
        self._busy = False
        self._assistant_widget: AssistantMessage | None = None
        self._tool_blocks: dict[str, ToolCallBlock] = {}
        self._spinner: SpinnerLine | None = None
        #: 忙碌期间提交的内容排在这里，本回合结束后依次发出。
        self._queue: list[str] = []
        self._palette_matches: list[Command] = []
        self._palette_index = 0
        self._quit_armed_at: float | None = None
        self.sub_title = str(session.project_dir)

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **PALETTE}

    def compose(self) -> ComposeResult:
        with MessageList(id="messages"):
            yield WelcomeBanner(
                project_dir=str(self._session.project_dir),
                provider_name=self._provider_name,
                model=self._model,
            )

        with Vertical(id="dock"):
            yield CommandPalette()
            yield Composer(id="composer")
            yield HintLine()

    def on_mount(self) -> None:
        self.query_one("#prompt", PromptInput).focus()

    # ------------------------------------------------------------ 动态绑定

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """按当前状态开合绑定。

        返回假时 ``App.run_action`` 会返回假，绑定链继续往下走——所以这里
        关掉一个绑定等于把它**让给**下层控件，而不是让它失效。
        """
        if action.startswith("palette_"):
            return self._palette_open

        if action == "interrupt":
            # 有选区时 ctrl+c 是「复制」：输入框里的选区归 TextArea，对话流里
            # 的选区归 Screen.action_copy_text。让位靠返回假——绑定链会继续往下
            # 走到 Screen 上那条 `ctrl+c,super+c`。
            prompt = self._query_prompt()
            if prompt is not None and not prompt.selection.is_empty:
                return False
            # 只在**真有选区**时让位。Screen.action_copy_text 在无选区时
            # `raise SkipAction()`，无条件让位的话空选区下 ctrl+c 会一路跳过，
            # 连退出都一并失效。
            return self.screen.get_selected_text() is None

        return True

    # ---------------------------------------------------------------- 状态

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def _palette_open(self) -> bool:
        return bool(self._palette_matches)

    def _query_prompt(self) -> PromptInput | None:
        try:
            return self.query_one("#prompt", PromptInput)
        except NoMatches:
            # 挂载完成前 check_action 也会被调到（比如启动时那次绑定求值）。
            return None

    def _hint(self) -> HintLine:
        return self.query_one("#hint", HintLine)

    def _messages(self) -> MessageList:
        return self.query_one("#messages", MessageList)

    def _set_busy(self, busy: bool) -> None:
        """切换忙碌态。

        **不动输入框的 disabled。** 以前忙碌时会 disable，靠失焦把 ``ctrl+x``
        让给 App 的绑定；现在忙碌期间要能继续打字排队，焦点必须留在输入框里，
        那条路走不通了——改由 ``PromptInput.action_cut`` 转交。这是输入法的
        硬约束（焦点即硬件光标），不是可以随手改回来的实现细节。
        """
        self._busy = busy
        if busy:
            self._hint().set_busy()
        else:
            self._hint().set_idle()

    async def _mount(self, widget: Widget) -> None:
        await self._messages().mount(widget)
        self._after_content()

    def _after_content(self) -> None:
        """内容变化后跟住底部，并刷新未读行数。"""
        messages = self._messages()
        if messages.follow:
            messages.scroll_end(animate=False)
            self._hint().set_unread(0)
            return

        # 未读不再单独计数：视口下面堆了多少行本来就是现成的，而且永远不会
        # 和真实位置对不上（自己计数迟早会因为折行、折叠而算错）。
        self._hint().set_unread(max(0, messages.max_scroll_y - messages.scroll_offset.y))

    def on_message_list_follow_changed(
        self, event: MessageList.FollowChanged
    ) -> None:
        event.stop()
        if event.follow:
            self._hint().set_unread(0)
        else:
            self._after_content()

    # ---------------------------------------------------------------- 输入

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """回车提交。

        输入法的候选确认键由终端自己消费，到不了这里；``PromptInput`` 里的
        Enter 绑定走的是 priority 路径，不会先被 ``TextArea`` 插成换行。
        """
        event.stop()

        if self._palette_open:
            # 面板开着时回车是「选中这条命令」，不是「发送输入框里的半截文字」。
            self._complete_palette()

        await self.submit_prompt()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        # 换了前缀就重排候选，选中项回到第一条。
        self._palette_index = 0
        self._sync_palette()

    def _sync_palette(self) -> None:
        prompt = self._query_prompt()
        palette = self.query_one(CommandPalette)
        matches = CommandPalette.matches(prompt.text if prompt else "")

        self._palette_matches = list(matches)
        if not matches:
            palette.hide()
            return

        self._palette_index = min(self._palette_index, len(matches) - 1)
        palette.show(matches, self._palette_index)

    def _complete_palette(self) -> None:
        prompt = self._query_prompt()
        if prompt is None or not self._palette_matches:
            return

        name = self._palette_matches[self._palette_index].name
        prompt.text = name
        prompt.move_cursor((0, len(name)))
        # 填完之后前缀已经唯一匹配，面板自己会收起来。
        self._sync_palette()

    def action_palette_move(self, offset: int) -> None:
        if not self._palette_matches:
            return
        size = len(self._palette_matches)
        self._palette_index = (self._palette_index + offset) % size
        self.query_one(CommandPalette).show(self._palette_matches, self._palette_index)

    def action_palette_accept(self) -> None:
        """tab：把选中的命令填进输入框，但不发送。"""
        self._complete_palette()

    async def submit_prompt(self) -> None:
        prompt = self.query_one("#prompt", PromptInput)
        content = prompt.text.strip()
        prompt.text = ""
        # 光标不是整数下标，得按 (行, 列) 放；清空文本本来就会归位，写出来
        # 是为了把「提交后光标回到左上角」这条不变量钉住。
        prompt.move_cursor((0, 0))
        self._sync_palette()

        if not content:
            return

        if content in {"/quit", "/exit"}:
            self.action_request_quit()
            return

        if content == "/clear":
            await self.action_clear()
            return

        if content == "/cancel":
            self.action_cancel()
            return

        if self._busy:
            # 排队而不是拒绝：把「想说下一句」和「再等一会儿」这两件事
            # 合并成一次输入，比弹个通知让人回来重打友好。
            self._queue.append(content)
            self._hint().set_message(f"已排队 {len(self._queue)} 条，本回合结束后发出")
            return

        await self._mount(UserMessage(content))
        self._set_busy(True)
        self._run_prompt(content)

    def action_cancel(self) -> None:
        if self._palette_open:
            self._dismiss_palette()
            return

        if self._busy:
            self._session.cancel()
            return

        # 空闲时 escape 是「回到最新」：滚上去看过历史之后按它回到底部。
        # 停在底部时静默——escape 很容易误触，不值得每次都弹提示。
        if not self._messages().follow:
            self._messages().scroll_end(animate=False)

    def action_interrupt(self) -> None:
        """ctrl+c：忙碌时中断，空闲时清草稿，再按一次才退出。

        退出要按两次是防止误触——这个键在终端里是肌肉记忆级的「停下」。
        """
        if self._palette_open:
            self._dismiss_palette()
            return

        if self._busy:
            self.action_cancel()
            return

        prompt = self._query_prompt()
        if prompt is not None and prompt.text:
            prompt.text = ""
            prompt.move_cursor((0, 0))
            self._sync_palette()
            self._hint().set_message("已清空输入 · 再按一次 ctrl+c 退出")
            return

        self._confirm_quit()

    def _confirm_quit(self) -> None:
        now = monotonic()
        if (
            self._quit_armed_at is not None
            and now - self._quit_armed_at <= QUIT_CONFIRM_WINDOW
        ):
            self.exit()
            return

        self._quit_armed_at = now
        self._hint().set_message("再按一次 ctrl+c 退出")
        self.set_timer(QUIT_CONFIRM_WINDOW, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed_at = None
        self._hint().clear_message()

    def _dismiss_palette(self) -> None:
        self._palette_matches = []
        self.query_one(CommandPalette).hide()

    async def action_clear(self) -> None:
        if self._busy:
            self.notify("请先等待任务结束或取消任务。")
            return

        self._spinner = None
        self._dismiss_palette()

        messages = self._messages()
        await messages.remove_children()
        await messages.mount(
            Static(
                Text("对话视图已清空；会话上下文仍然保留。", style=INACTIVE),
                classes="welcome",
            )
        )
        messages.scroll_end(animate=False)
        self._hint().clear_message()

    def action_toggle_tools(self) -> None:
        """全部工具结果一起折叠/展开。

        只要还有没展开的就先全展开——这样一次按键的结果是可预期的，
        而不用管当前是哪种混合状态。
        """
        blocks = [block for block in self.query(ToolCallBlock) if block.has_result]
        if not blocks:
            self.notify("这一轮还没有工具结果。")
            return

        expand = any(not block.is_expanded for block in blocks)
        for block in blocks:
            block.set_expanded(expand)
        self._after_content()
        self.notify("已展开全部工具结果" if expand else "已折叠全部工具结果")

    def action_request_quit(self) -> None:
        if self._busy:
            self._session.cancel()
        self.exit()

    # ---------------------------------------------------------------- 视图

    async def _hide_spinner(self) -> None:
        if self._spinner is None:
            return
        spinner, self._spinner = self._spinner, None
        await spinner.remove()

    async def _show_spinner(self, label: str) -> None:
        # 每次都重挂，好让 spinner 永远是 #messages 的最后一个子节点。
        # 一轮里会经历「思考 → 执行工具 → 再思考」，spinner 必须跟着挪到
        # 当前动作下面；复用旧实例会把它留在工具块上方。
        await self._hide_spinner()
        spinner = SpinnerLine(label)
        self._spinner = spinner
        await self._mount(spinner)

    # ---------------------------------------------------------------- 渲染

    async def _render_event(self, event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            await self._show_spinner("正在思考…")

        elif isinstance(event, MessageUpdateEvent):
            await self._render_assistant(event.assistant_message_event)

        elif isinstance(event, ToolExecutionStartEvent):
            block = ToolCallBlock(event.call)
            self._tool_blocks[event.call.id] = block
            await self._mount(block)
            # 工具块说明「在跑什么」，spinner 说明「还活着」。只有静态的
            # 「运行中…」时，一个跑三十秒的工具和卡死看起来没区别。
            await self._show_spinner(f"正在执行 {event.call.name}…")

        elif isinstance(event, ToolExecutionEndEvent):
            await self._hide_spinner()
            started = self._tool_blocks.get(event.result.tool_call_id)
            if started is None:
                await self._mount(Static(Text(event.result.content, style=INACTIVE)))
            else:
                started.set_result(event.result)
                self._after_content()

        elif isinstance(event, AgentEndEvent):
            await self._hide_spinner()
            if event.reason == "cancelled":
                self._hint().set_message("已取消")
            elif event.reason == "error":
                self._hint().set_message(
                    f"运行失败：{event.error_message or '未知错误'}", error=True
                )

    async def _render_assistant(self, event: AssistantMessageEvent) -> None:
        if isinstance(event, AssistantStartEvent):
            # 模型 Start 之后要静默一阵才吐第一个字。这期间界面上该是
            # 「✻ 正在思考…」，而不是一个孤零零、没有任何动静的空 ⏺ 行——
            # 所以这里既不挂消息行，也不收 spinner，只重置指针。
            self._assistant_widget = None
            await self._show_spinner("正在思考…")

        elif isinstance(event, TextDeltaEvent):
            await self._hide_spinner()
            if self._assistant_widget is None:
                self._assistant_widget = AssistantMessage()
                await self._mount(self._assistant_widget)

            self._assistant_widget.append_text(event.delta)
            self._after_content()

        elif isinstance(event, AssistantDoneEvent):
            # 整轮只调了工具、没有文字时不留空行。
            if self._assistant_widget is not None:
                # 节流的重绘可能还压着最后一个增量，收尾时补上。
                self._assistant_widget.flush()
                if not self._assistant_widget.body_text:
                    self._assistant_widget.display = False

    async def _run_turn(self, content: str) -> bool:
        """跑一轮（一条输入 → 一次 agent 循环），返回能否接着抽队列。

        ``run_agent_loop`` 取消时先 ``yield`` 一个 ``reason="cancelled"`` 的
        ``AgentEndEvent`` 再把 ``CancelledError`` 抛出来，所以两条路都得接：
        提示由事件那条路给，这里只负责决定还继不继续。
        """
        saw_end_event = False
        self._assistant_widget = None
        self._tool_blocks = {}

        try:
            async with aclosing(self._session.prompt(content)) as stream:
                async for event in stream:
                    try:
                        await self._render_event(event)
                    except Exception as exc:  # noqa: BLE001 - 渲染边界
                        # 界面自己的异常不能报成「运行失败」：那会把布局 bug
                        # 和真正的模型/工具错误混成一句话，两边都没法查。
                        self._hint().set_message(f"界面渲染失败：{exc}", error=True)
                        await self._mount(Static(Text(f"界面渲染失败\n{exc}", style=ERROR)))
                        return False

                    if isinstance(event, AgentEndEvent):
                        saw_end_event = True
        except asyncio.CancelledError:
            if not saw_end_event:
                self._hint().set_message("已取消")
            return False
        except Exception as exc:  # noqa: BLE001 - UI error boundary
            if not saw_end_event:
                self._hint().set_message(f"运行失败：{exc}", error=True)
                await self._mount(Static(Text(f"运行失败\n{exc}", style=ERROR)))
            return False

        return True

    @work(group="agent", exclusive=True, exit_on_error=False)
    async def _run_prompt(self, content: str) -> None:
        """一条 worker 把排队的内容按顺序抽干。

        不在这里递归调用自己：``@work(exclusive=True)`` 会取消同组里正在运行
        的 worker——也就是它自己。队列只能由同一个 worker 顺序消费。
        """
        try:
            current = content
            while True:
                if not await self._run_turn(current):
                    break
                if not self._queue:
                    break

                current = self._queue.pop(0)
                # 出队时必须补挂用户消息：提交那一刻忙碌，``submit_prompt``
                # 只做了入队，气泡还没画。
                await self._mount(UserMessage(current))
                remaining = len(self._queue)
                if remaining:
                    self._hint().set_message(f"队列中还有 {remaining} 条")
                else:
                    self._hint().clear_message()
        finally:
            self._assistant_widget = None
            await self._hide_spinner()

            if self._queue:
                # 中途取消/出错：没轮到的排队内容不会自己消失，得说清楚。
                dropped = len(self._queue)
                self._queue.clear()
                self._hint().set_message(f"已中断，丢弃 {dropped} 条排队内容")
            self._set_busy(False)
