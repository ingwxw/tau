"""对话流里的各类 widget。

视觉语言照搬 Claude Code：``⏺`` 标记一次动作（助手回复或工具调用），
``⎿`` 标记工具结果，``✻`` 标记进行中的 spinner。

正文分两种：助手输出是 Markdown，交给 ``markdown.render_markdown``；用户输入
和工具输出是纯文本，一律用 ``rich.text.Text`` 承载而不是 markup 字符串——
这些内容来自外部，含 ``[`` 时会被 Rich 当成标记解析。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.content import Content
from textual.geometry import Size
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static, TextArea

from tau_agent.messages import ToolCall, ToolResultMessage
from tau_coding.tui.markdown import render_markdown
from tau_coding.tui.theme import (
    APP_VERSION,
    CLAUDE,
    CLAUDE_SHIMMER,
    ERROR,
    INACTIVE,
    SUBTLE,
)

#: 三个标记字形都取自 Claude Code：``⏺`` 是它的助手行首、``❯`` 是用户行首
#: （U+276F，ASCII 终端上它退化成 ``>``，这里不跟），``⎿`` 是工具结果行首。
#: 三个都是单列宽，改了不用重算列宽。
MARK_ACTION = "⏺"
MARK_USER = "❯"
MARK_RESULT = "⎿"

#: 单行工具结果摘要的截断长度，避免撑破窄终端。
SUMMARY_LIMIT = 120

#: 工具结果折叠时展示的行数。
COLLAPSED_LINES = 1

#: 展开后最多展示的行数，再长仍然截断——工具能吐出一整个文件。
EXPANDED_LINES = 40

#: Claude Code 的 spinner 帧序列。
SPINNER_FRAMES = "·✢✳✶✽✻"

#: 终端宽度低于此值时横幅去掉字符画，只留文字。
BANNER_COMPACT_WIDTH = 44

#: τ 的块状字符画，三行；宽度用于和右侧文字列对齐。
TAU_ART = (" ▄▄▄▄▄▄▄", "   ███", "    █")
_ART_WIDTH = max(len(line) for line in TAU_ART)

#: 助手正文的最短重绘间隔。Rich 的 Markdown 每次都要重解析整篇，
#: 16KB 单次约 21ms，按 delta 逐字重解析会把一核跑满。
MARKDOWN_FLUSH_INTERVAL = 0.05


def format_tool_call(call: ToolCall) -> str:
    """``read(src/x.py)`` / ``edit(path=a.py, old=b)``。"""
    arguments = call.arguments
    if len(arguments) == 1:
        (value,) = arguments.values()
        rendered = f"{value}"
    else:
        rendered = ", ".join(f"{key}={value}" for key, value in arguments.items())
    return f"{call.name}({rendered})"


def result_lines(content: str) -> list[str]:
    """工具输出按行切开，丢掉空行。"""
    return [line.rstrip() for line in content.splitlines() if line.strip()]


def split_summary(content: str) -> tuple[str, int]:
    """(首行摘要, 还有多少行没显示)。"""
    lines = result_lines(content)
    if not lines:
        return "(无输出)", 0

    head = lines[0].strip()
    if len(head) > SUMMARY_LIMIT:
        head = head[:SUMMARY_LIMIT] + "…"
    return head, max(0, len(lines) - COLLAPSED_LINES)


def summarize_result(content: str) -> str:
    """折叠态的一行摘要：首行 + 剩余行数。

    Claude Code 折叠工具结果时也是这个形状——一行摘要加上「还有多少没显示」，
    并且明说按哪个键能展开，否则那一行看起来就像全部输出。
    """
    head, hidden = split_summary(content)
    if hidden == 0:
        return head
    return f"{head} … +{hidden} 行 (ctrl+o 展开)"


def preview_result(content: str, *, expanded: bool, style: str = INACTIVE) -> Text:
    """工具结果的正文。

    折叠时只有一行摘要；展开时给出前 ``EXPANDED_LINES`` 行，再长仍然截断，
    并在末尾说明还剩多少——否则一个读整个文件的 ``read`` 会把对话流冲掉。

    ``style`` 是正文的底色（成功取灰、失败取红）。「还有多少行 / 按哪个键」
    那截用 ``SUBTLE`` 单独压暗一档：它是次要提示，不该和内容一样响。
    """
    if expanded:
        lines = result_lines(content)
        text = Text("\n".join(lines[:EXPANDED_LINES]), style=style)
        if len(lines) > EXPANDED_LINES:
            text.append(
                f"\n… 还有 {len(lines) - EXPANDED_LINES} 行未显示", style=SUBTLE
            )
        return text

    head, hidden = split_summary(content)
    text = Text(head, style=style)
    if hidden:
        text.append(f" … +{hidden} 行 (ctrl+o 展开)", style=SUBTLE)
    return text


class PromptInput(TextArea):
    """提示编辑器：软换行、高度自适应，硬件光标交给 Textual 维护。

    用 ``TextArea`` 而不是 ``Input``，是因为 ``Input`` 的渲染写死了
    ``no_wrap``（``_input.py:687``），物理上无法软换行，超长文本只会被
    ``overflow-x: hidden`` 裁掉。``TextArea`` 的 ``soft_wrap`` 默认为真，
    并且同样维护 ``cursor_screen_offset``，输入法要的硬件光标锚点还在。
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # 必须 priority。``TextArea._on_key`` 会把 Enter 换成 ``"\n"``，
        # 途中 ``event.stop()`` 掉，事件根本冒不到 ``App._on_key``——而非
        # priority 的绑定只在那条路径上被查，写上去就是死代码。
        Binding("enter", "submit", "发送", show=False, priority=True),
        Binding("shift+enter", "newline", "换行", show=False, priority=True),
        Binding("ctrl+j", "newline", "换行", show=False, priority=True),
    ]

    class Submitted(Message):
        """Enter 提交。``TextArea`` 没有内建的提交事件，只能自己发。"""

        def __init__(self, text_area: PromptInput) -> None:
            self.text_area = text_area
            super().__init__()

        @property
        def control(self) -> PromptInput:
            return self.text_area

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("compact", True)
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        # 设成 "indent" 会让 TextArea 连 escape 一起吞掉，App 的取消就没了。
        kwargs.setdefault("tab_behavior", "focus")
        # 不画占位文字：原生输入法在 Textual 文档之外绘制预编辑串，
        # 占位文字会和它重叠，看起来像组合文本的一部分。
        kwargs.setdefault("placeholder", "")
        # 光标所在行默认铺一道 $boost 底色带，而且失焦时也照画。实色带子正是
        # 输入法问题的成因。只能在构造时给：它是没有 watcher 的 reactive，
        # 运行中再赋值不会清掉 _line_cache，带子依旧在。
        kwargs.setdefault("highlight_cursor_line", False)
        super().__init__(**kwargs)

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    def action_newline(self) -> None:
        self.insert("\n")

    def action_cut(self) -> None:
        """只剪切真正选中的内容，没选中就什么都不做。

        ``TextArea.action_cut`` 在无选区时会删掉光标所在的整行。``ctrl+x``
        在本应用里是「中断」，照搬过去会让想中断的人把正在写的草稿整行删掉。
        这里对齐 ``Input`` 的语义（它无选区时是空操作）。

        忙碌时整条 ``ctrl+x`` 都得让位给中断：回合进行中输入框不再被 disable
        （要支持排队），焦点一直留在 ``#prompt`` 上，于是事件根本冒不到 App
        的 ``ctrl+x`` 绑定——只能由这里转交。
        """
        app = self.app
        if getattr(app, "is_busy", False):
            app.action_cancel()
            return
        if not self.selection.is_empty:
            super().action_cut()


class WelcomeBanner(Static):
    """启动横幅：左侧 τ 字符画，右侧版本与模型，下方 cwd。

    内容一次性预渲染成多行 ``rich.text.Text``，不靠 Textual 拼两列，
    窄终端下不会错位；宽度不足时降级成不含字符画的紧凑版。
    """

    def __init__(self, *, project_dir: str, provider_name: str, model: str) -> None:
        super().__init__("", markup=False, classes="welcome")
        self._project_dir = project_dir
        self._provider_name = provider_name
        self._model = model
        self._compact: bool | None = None
        self._last_width = 0

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_banner()

    def _refresh_banner(self) -> None:
        # 名字不能叫 _render —— 那是 Widget 用来产出可视内容的内部钩子，
        # 覆写后 Textual 量不到 auto 高度。
        width = self.size.width
        compact = width < BANNER_COMPACT_WIDTH
        if compact == self._compact and width == self._last_width:
            return
        self._compact = compact
        self._last_width = width
        self.update(Text("\n").join(self._lines(compact, width)))

    def _cwd_line(self, width: int) -> Text:
        prefix = "  cwd: "
        path = self._project_dir
        available = width - len(prefix)

        # 窄终端下先退化成 …/目录名，再退化才硬截断，避免 cwd 折成好几行。
        if available > 1 and len(path) > available:
            name = Path(path).name or path
            path = f"…/{name}"
            if len(path) > available:
                path = path[: available - 1] + "…"

        return Text(f"{prefix}{path}", style=INACTIVE)

    def _lines(self, compact: bool, width: int) -> list[Text]:
        identity = f"{self._model} · {self._provider_name}"

        if compact:
            lines = [
                Text(f"Tau v{APP_VERSION}", style="bold"),
                Text(identity, style=INACTIVE),
            ]
        else:
            right = (
                (f"Tau v{APP_VERSION}", "bold"),
                (identity, INACTIVE),
                ("", INACTIVE),
            )
            lines = []
            for art, (label, style) in zip(TAU_ART, right):
                line = Text(art.ljust(_ART_WIDTH), style=CLAUDE)
                line.append("  ")
                line.append(label, style=style)
                lines.append(line)

        lines.append(Text(""))
        lines.append(self._cwd_line(width))
        return lines


class BodyColumn(Static):
    """正文列。

    Markdown 按宽度预渲染，所以不能像普通 ``Static`` 那样把渲染结果存下来当
    内容——宽度一变，行就得重折。这里改成**按需渲染**：Textual 来问高度时用它
    给的宽度渲染，绘制时用自己实际的宽度渲染，两个答案永远出自同一个宽度。

    不用「``on_resize`` 里 ``update()``」那条路。从 resize 处理器里再申请一次
    布局会被 Textual 合并掉：``Widget.refresh`` 只在 ``_layout_required`` 由假
    转真时自增 ``_layout_updates``，已经是真就不再计数，而布局请求是记账消费
    的，被并掉的那次不会补发。结果是正文永远停在高 1 行——内容其实已经渲染好
    了，只是被裁掉，``region.height`` 再也不动。这个 bug 是间歇的（取决于
    resize 和布局谁先到），实测 60 次里中 2 次。
    """

    def __init__(self, owner: MarkedRow) -> None:
        super().__init__("", markup=False, classes="body")
        self._owner = owner
        #: ``(宽度, 渲染结果)``。只留最近一版：宽度在一次布局里是稳定的，
        #: 来回切宽度的场景不存在。
        self._rendered: tuple[int, Content] | None = None

    def content_for(self, width: int) -> Content:
        """按 ``width`` 渲染，同一个宽度只算一次。"""
        if self._rendered is None or self._rendered[0] != width:
            self._rendered = (width, self._owner.render_body(width))
        return self._rendered[1]

    def invalidate(self) -> None:
        """源码变了，丢掉缓存的那一版。"""
        self._rendered = None

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        # 宽度还没量出来时不要渲染：``render_markdown`` 拿到 0 会返回空
        # ``Content``，而空 ``Content`` 的高度是 1——正是上面那个「卡在高 1 行」
        # 的样子，别再自己造一个。
        if not width:
            return 0
        return self.content_for(width).get_height(self.styles, width)

    def render(self) -> Content:
        return self.content_for(self.content_size.width or self.size.width)


class MarkedRow(HorizontalGroup):
    """``⏺ 正文`` 两列行：定宽标记列 + 正文列。

    用两列而不是把标记拼进正文，是为了让折行后的续行对齐到正文列，
    而不是回到标记下面。

    基类用 ``HorizontalGroup`` 而非 ``Horizontal``：后者的默认高度是
    ``1fr``，在 ``height: auto`` 的父容器里会把整块撑开。
    """

    MARK = MARK_ACTION
    CSS_CLASS = ""

    #: 正文是否按 Markdown 渲染。用户输入不是 Markdown——里面随手打的
    #: ``*`` 和 ``_`` 会被当成强调标记，把原话改得面目全非。
    RENDER_MARKDOWN: ClassVar[bool] = False

    def __init__(self, body: str = "") -> None:
        super().__init__(classes=self.CSS_CLASS)
        self._body = body
        self._body_widget: BodyColumn | None = None
        self._dirty = False
        self._flush_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(self.MARK, markup=False, classes="mark")
        yield BodyColumn(self)

    def on_mount(self) -> None:
        self._body_widget = self.query_one(BodyColumn)
        self._refresh()

    def on_unmount(self) -> None:
        # 运行中被移除（清屏、销毁）必须显式停表，否则 timer 还会来敲一次。
        self._stop_flush_timer()

    @property
    def body_text(self) -> str:
        """原始的 Markdown 源码，不是渲染结果。"""
        return self._body

    def append_text(self, delta: str) -> None:
        self._body += delta
        self._dirty = True

        # 换行是块边界，立刻重绘——流式时「一行一行长出来」比「每 50ms 跳
        # 一下」更接近模型的产出节奏。其余情况合并到下一个时间片。
        if "\n" in delta:
            self.flush()
        elif self._flush_timer is None:
            self._flush_timer = self.set_timer(
                MARKDOWN_FLUSH_INTERVAL, self.flush
            )

    def flush(self) -> None:
        """把待渲染的增量落到屏幕上。回合结束时由 App 调一次收尾。"""
        self._stop_flush_timer()
        if not self._dirty:
            return
        self._dirty = False
        self._refresh()

    def _stop_flush_timer(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None

    def render_body(self, width: int) -> Content:
        """正文内容。Markdown 要用宽度排版，纯文本不用。

        两者都返回 ``Content``：它是 Textual 唯一可选的渲染结果。用户输入
        不能按 Markdown 渲染——里面随手打的 ``*`` 和 ``_`` 会被当成强调标记，
        把原话改得面目全非。
        """
        if self.RENDER_MARKDOWN:
            return render_markdown(self._body, width)
        return Content(self._body)

    def _refresh(self) -> None:
        if self._body_widget is None:
            return
        # 这里只丢缓存 + 申请布局，渲染本身交给 ``BodyColumn``——它知道宽度。
        self._body_widget.invalidate()
        self._body_widget.refresh(layout=True)


class UserMessage(MarkedRow):
    MARK = MARK_USER
    CSS_CLASS = "user-message"


class AssistantMessage(MarkedRow):
    MARK = MARK_ACTION
    CSS_CLASS = "assistant-message"
    RENDER_MARKDOWN = True


class ToolCallBlock(Vertical):
    """``⏺ read(path)`` 加 ``  ⎿ 结果``。

    结果默认折叠成一行摘要，``ctrl+o`` 展开。展开状态记在块自己身上，
    所以切换是「各自记住」而不是全局一刀切。
    """

    def __init__(self, call: ToolCall) -> None:
        super().__init__(classes="tool-block")
        self._call = call
        self._result: ToolResultMessage | None = None
        self._expanded = False

    def compose(self) -> ComposeResult:
        with HorizontalGroup(classes="tool-head"):
            yield Static(MARK_ACTION, markup=False, classes="mark")
            yield Static(format_tool_call(self._call), markup=False, classes="body")
        with HorizontalGroup(classes="tool-result"):
            yield Static(MARK_RESULT, markup=False, classes="result-mark")
            yield Static("", markup=False, classes="body")

    def on_mount(self) -> None:
        self.set_running()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def has_result(self) -> bool:
        return self._result is not None

    def set_running(self) -> None:
        self.remove_class("tool-error")
        self._set_result(Text("运行中…", style=INACTIVE))

    def set_result(self, result: ToolResultMessage) -> None:
        self._result = result
        if result.is_error:
            self.add_class("tool-error")
        else:
            self.remove_class("tool-error")
        self._render_result()

    def set_expanded(self, expanded: bool) -> None:
        """折叠/展开。还没跑完的块不动——它本来就只有「运行中…」一行。"""
        if self._result is None or expanded == self._expanded:
            return
        self._expanded = expanded
        self._render_result()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def _render_result(self) -> None:
        result = self._result
        if result is None:
            return

        if result.is_error:
            # 报错要能一眼看见，所以整块（含标记）都染红，而不只是正文。
            text = Text("Error: ", style=ERROR)
            text.append_text(
                preview_result(result.content, expanded=self._expanded, style=ERROR)
            )
        else:
            text = preview_result(result.content, expanded=self._expanded)
        self._set_result(text)

    def _set_result(self, text: Text) -> None:
        self.query_one(".tool-result .body", Static).update(text)


class SpinnerLine(Static):
    """``✻ 正在思考… (3s)``，帧与耗时由 interval 驱动。"""

    def __init__(self, label: str = "正在思考…") -> None:
        super().__init__("", markup=False, classes="spinner")
        self._label = label
        self._started = monotonic()
        self._frame = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        # 运行中被移除时（取消、清屏）必须显式停表，否则 interval 会继续跑。
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @property
    def is_animating(self) -> bool:
        return self._timer is not None

    def _tick(self) -> None:
        frame = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        self._frame += 1

        text = Text()
        text.append(frame, style=CLAUDE if self._frame % 2 else CLAUDE_SHIMMER)
        text.append(f" {self._label}", style=INACTIVE)
        text.append(f" ({int(monotonic() - self._started)}s)", style=INACTIVE)
        # layout=False：高度恒为 1，每 100ms 重新排版纯属浪费。
        self.update(text, layout=False)


#: 空闲时的快捷键提示。
HINT_IDLE = "ctrl+x 中断 · ctrl+o 展开结果 · ctrl+l 清屏 · ctrl+q 退出"


class MessageList(VerticalScroll):
    """对话流。滚动位置决定要不要继续跟随底部。

    「跟不跟随」不能靠监听滚轮事件来维护：键盘、拖滚动条、``scroll_end``
    都会改 ``scroll_y``，只认一种输入源迟早会跟真实位置脱节。``watch_scroll_y``
    是这些路径的公共汇合点——最后一次滚动落在底部就跟随，否则停住。

    内容变长只会抬高 ``max_scroll_y`` 而不动 ``scroll_y``，所以**追加内容本身
    不会**触发这里；这正是想要的：跟着底部时接着跟，滚上去看了就停住。
    """

    class FollowChanged(Message):
        """跟随状态变了。"""

        def __init__(self, follow: bool) -> None:
            self.follow = follow
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.follow = True

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        follow = self.is_vertical_scroll_end
        if follow != self.follow:
            self.follow = follow
            self.post_message(self.FollowChanged(follow))


class HintLine(Static):
    """输入框下面那行提示。

    四种状态共用一行，取值优先级：**一次性消息 > 忙碌 > 空闲**。未读计数是
    独立的前缀——用户滚上去看历史时，最需要知道的就是「下面又堆了多少」，
    这件事和当前是忙是闲无关。

    计时不放在这里就只剩 spinner 那一处，而工具执行期间 spinner 会换位置；
    固定在底部的这一行才是「这个回合跑了多久」唯一稳定的落点。
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            Text(HINT_IDLE, style=INACTIVE), markup=False, id="hint", **kwargs
        )
        self._message: tuple[str, bool] | None = None
        self._busy_since: float | None = None
        self._unread = 0
        self._timer: Timer | None = None

    def on_unmount(self) -> None:
        self._stop_timer()

    @property
    def is_busy(self) -> bool:
        return self._busy_since is not None

    def set_idle(self) -> None:
        """结束忙碌态。**不**清掉一次性消息——那是本回合的结论。"""
        self._busy_since = None
        self._stop_timer()
        self._refresh_text()

    def set_busy(self) -> None:
        # 开新回合先清掉上一轮的「已取消 / 运行失败」，否则会挂在下面误导人。
        self._message = None
        self._busy_since = monotonic()
        self._ensure_timer()
        self._refresh_text()

    def set_message(self, content: str, *, error: bool = False) -> None:
        self._message = (content, error)
        self._refresh_text()

    def clear_message(self) -> None:
        self._message = None
        self._refresh_text()

    def set_unread(self, count: int) -> None:
        if count == self._unread:
            return
        self._unread = count
        self._refresh_text()

    def _ensure_timer(self) -> None:
        if self._timer is None:
            self._timer = self.set_interval(0.5, self._refresh_text)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _refresh_text(self) -> None:
        chunks: list[tuple[str, str]] = []

        if self._unread:
            chunks.append((f"↓ 还有 {self._unread} 行 · esc 到底部", CLAUDE))

        if self._message is not None:
            content, error = self._message
            chunks.append((content, ERROR if error else INACTIVE))
        elif self._busy_since is not None:
            elapsed = int(monotonic() - self._busy_since)
            chunks.append((f"esc 中断 · 已运行 {elapsed}s", INACTIVE))
        else:
            chunks.append((HINT_IDLE, INACTIVE))

        text = Text()
        for position, (chunk, style) in enumerate(chunks):
            if position:
                text.append(" · ", style=SUBTLE)
            text.append(chunk, style=style)

        # layout=False：高度被 CSS 钉成 1，重排纯属浪费。这条每 0.5s 跑一次。
        self.update(text, layout=False)


@dataclass(frozen=True)
class Command:
    """斜杠命令。"""

    name: str
    summary: str


COMMANDS: tuple[Command, ...] = (
    Command("/clear", "清空对话视图，保留会话上下文"),
    Command("/cancel", "中断当前任务"),
    Command("/quit", "退出 Tau"),
)

#: 命令面板最多同时列几条。
PALETTE_LIMIT = 6


class CommandPalette(Static):
    """输入 ``/`` 时浮在输入框上方的命令面板。

    刻意不用 ``OptionList``：那是个可聚焦控件，会把焦点从 ``#prompt`` 抢走，
    而硬件光标必须一直留在输入框里——macOS 输入法在光标处绘制预编辑串。
    所以选中项由 App 维护，这里只负责画。
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", markup=False, id="palette", **kwargs)
        self.display = False

    @property
    def is_open(self) -> bool:
        return self.display

    @staticmethod
    def matches(text: str) -> list[Command]:
        """按已输入的 ``/xxx`` 前缀过滤。空列表表示不该弹。"""
        if not text.startswith("/") or len(text) > 24:
            return []
        if any(char.isspace() for char in text):
            return []

        found = [command for command in COMMANDS if command.name.startswith(text)]
        # 已经打全了就别再挡着——面板的高度会顶动输入框的位置。
        if len(found) == 1 and found[0].name == text:
            return []
        return found[:PALETTE_LIMIT]

    def show(self, matches: list[Command], index: int) -> None:
        lines: list[Text] = []
        for position, command in enumerate(matches):
            line = Text()
            selected = position == index
            line.append("▸ " if selected else "  ", style=CLAUDE if selected else INACTIVE)
            line.append(
                command.name.ljust(10),
                style=CLAUDE if selected else "bold",
            )
            line.append(command.summary, style=INACTIVE)
            lines.append(line)

        self.update(Text("\n").join(lines))
        self.display = True

    def hide(self) -> None:
        self.display = False


class Composer(Vertical):
    """输入区：上下两条横线由本容器绘制，``#prompt`` 自身无边框无底色。

    高度不写死——``#prompt`` 软换行后 ``TextArea`` 的 ``virtual_size``
    跟着内容走，容器的高度自动跟上；只在 CSS 里封一个顶。
    """

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id="prompt-row"):
            yield Static(MARK_USER, markup=False, id="prompt-prefix")
            yield PromptInput(id="prompt")
