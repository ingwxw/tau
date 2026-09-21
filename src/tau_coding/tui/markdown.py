"""助手输出的 Markdown 渲染。

助手正文是 Markdown，增量到达。``rich.markdown.Markdown`` 每次构造都要重解析
整篇文档，实测 16KB 单次约 21ms（构造 + 排版），按 delta 逐字重解析会把一核
跑满。所以这里只负责「把一段源码变成可渲染结果」这个纯函数部分，节流交给
``widgets.MarkedRow``。

**出口是 ``textual.content.Content``，不是 Rich 对象。** 这是硬要求，不是风格
选择：``visualize()`` 会把任何 Rich 可渲染对象包成 ``RichVisual``，而
``RichVisual.render_strips`` 直接 ``Strip(line)`` 包装，**不带
``style._meta["offset"]``**——``Compositor.get_widget_and_offset_at`` 靠这个 meta
定位内容控件，拿不到就退化成容器级选区，于是鼠标拖过去什么都选不中、
``ctrl+c`` 也复制不出东西。``Content`` 是 Textual 唯一可选的渲染结果
（``Static`` 持 ``str``/``Text`` 时走的正是它）。

所以流程是「LaTeX 预处理 → Rich 解析排版 → 拆成 segment → 拼回 ``Content``」：
Rich 的 Markdown 排版能力照用，只把出口换掉。

样式来自 ``MARKDOWN_THEME``，**不是** Rich 的 ``DEFAULT_STYLES``。Rich 的
``Markdown`` 用 ``console.get_style("markdown.h2")`` 这类查找解析元素样式，
跟 ``code_theme`` 无关，所以不给 console 挂主题就会拿到出厂值：品红下划线的
h2、品红的引用块、青色的列表编号和表格边框。

``MARKDOWN_THEME`` 与 ``CODE_STYLE_MAP`` 都是照 Claude Code 2.1.276 的
Markdown 渲染器（``JT``）和它的 highlight.js scope 表**逐条**抄的，不是凭感觉
配的。三条要点：

- **代码块的字色是 ANSI 具名色，不是十六进制。** Claude Code 用的是 chalk 的
  ``blue`` / ``cyan`` / ``green`` / ``red`` / ``yellow`` / ``grey``，也就是
  ``ESC[34m`` / ``36`` / ``32`` / ``31`` / ``33`` / ``90``——**颜色由终端自己的
  调色板决定**，它没有 RGB 配色表。照抄这一点比自己挑一套十六进制更接近原样，
  也顺带解决了「代码块是霓虹色」：monokai 那六个固定真彩色（``#ff4689`` 关键字、
  ``#66d9ef`` 函数、``#a6e22e`` 数字）在任何终端上都一样扎眼，ANSI 色则跟着
  用户已经调好的终端主题走。
- **标题不带颜色。** h1 是 ``bold + italic + underline``，h2 及以下是 ``bold``，
  分级靠字重不靠色相。链接是 ``bright_blue``（chalk ``blueBright``），**没有
  下划线**。
- **符号不上色。** 引用块是「``▎`` 压暗 + 正文斜体」，列表符号是 ``-``、
  ``hr`` 是字面量 ``---``，都不带颜色。

``TauMarkdown`` 靠 ``Markdown.elements`` 这个类变量换掉负责的 Element 类，一共
改 Rich 的五处默认表现：

- **标题不居中。** Rich 的 ``Heading.LEVEL_ALIGN`` 把 h1 定成居中，在对话流里
  会跟着气泡宽度左右横跳。
- **代码块不铺底色、不留上下空行。** 底色来自 pygments 主题的
  ``background_color``（monokai 是 ``#272822``）；``ANSISyntaxTheme`` 的底色本来
  就是空的，``padding=0`` 去掉上下各一行的空行。
- **引用块用 ``▎`` 且正文斜体**（Rich 写死 ``▌``，且整段只压暗不变斜体）。
- **列表符号是 ``-`` 和 ``1.``**（Rich 写死 ``" • "``，有序列表还不带句点）。
- **``hr`` 是字面量 ``---``**（Rich 画一条铺满整行的 ``─────``）。

``width`` 是渲染输入而不是结果属性：Rich 在排版时就按宽度折好行了，所以宽度
一变必须重渲（``widgets.BodyColumn`` 盯这件事）。也让 ``Content`` 拿到的是已经
折好的行，Textual 自己的折行不会再动它。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from pygments.token import Token
from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import (
    BlockQuote,
    CodeBlock,
    Heading,
    HorizontalRule,
    ListItem,
    Markdown,
    loop_first,
)
from rich.segment import Segment
from rich.style import Style
from rich.syntax import ANSISyntaxTheme, Syntax
from rich.text import Text
from rich.theme import Theme
from textual.content import Content, Span
from textual.style import Style as TuiStyle

from tau_coding.tui.latex import convert
from tau_coding.tui.theme import PERMISSION, SUBTLE, TEXT

__all__ = [
    "CODE_STYLE_MAP",
    "MARKDOWN_THEME",
    "TauCodeTheme",
    "TauMarkdown",
    "render_markdown",
]

#: Markdown 元素配色。覆盖 Rich ``DEFAULT_STYLES`` 里那套出厂霓虹色。
#:
#: 分层靠字重，不靠色相：标题只有粗体（h1 另加斜体和下划线），符号一律不上色，
#: 整篇只有行内代码（``permission``）和链接（``bright_blue``）是有色的。
#: 这正是 Claude Code ``JT`` 里的做法。
MARKDOWN_THEME = Theme(
    {
        "markdown.h1": "bold italic underline",
        "markdown.h2": "bold",
        "markdown.h3": "bold",
        "markdown.h4": "bold",
        "markdown.h5": "bold",
        "markdown.h6": "bold",
        "markdown.h7": "bold",
        # 默认是 ``none``，但 h1 那条 ``underline`` 一旦被人改回来就会在这里露出来。
        "markdown.h1.border": "none",
        # 正文斜体；``▎`` 由 _QuotedBlockQuote 自己加 dim。
        "markdown.block_quote": "italic",
        "markdown.hr": "none",
        # 默认的 ``cyan`` 不只染符号，会顺着继承把列表正文一起染青。
        "markdown.list": "none",
        "markdown.item": "none",
        # 出厂值是 ``bold``（符号）和 ``cyan``（编号），Claude Code 两个都不上色。
        "markdown.item.bullet": "none",
        "markdown.item.number": "none",
        # chalk 的 ``blueBright``（SGR 94），无下划线。``link_url`` 也得设——
        # Rich 真正拿去着色的其实是它，只改 ``markdown.link`` 不生效。
        "markdown.link": "bright_blue",
        "markdown.link_url": "bright_blue",
        # 行内代码。Claude Code ``JT`` 里 ``codespan`` 用主题键 ``permission``。
        "markdown.code": PERMISSION,
        "markdown.code_block": "none",
        # Claude Code 不渲染表格（``JT`` 里没有 table 分支），没有对齐目标，
        # 沿用本项目原来的配色。
        "markdown.table.border": SUBTLE,
        "markdown.table.header": f"bold {TEXT}",
        "markdown.kbd": f"bold {TEXT}",
    }
)

#: 代码块的字色：Claude Code 的 highlight.js scope → chalk 颜色表。
#:
#: ``rich.syntax.PygmentsSyntaxTheme`` 内部写死 ``color="#" + color``，只吃十六
#: 进制，给不了 ANSI 具名色，所以这里走 ``ANSISyntaxTheme``——``Syntax.get_theme``
#: 对 ``SyntaxTheme`` 实例是原样返回的，``Markdown(code_theme=...)`` 一路透传。
#:
#: 没列出来的 token 一律不上色（``ANSISyntaxTheme`` 未命中时返回
#: ``Style.null()``），继承正文色——和 Claude Code「没有匹配 scope 就不上色」一致。
#: **特别注意不要给 ``Token.Name`` 上色**：hljs 的 ``variable`` / ``params`` 都是
#: 不上色的，把整个 ``Token.Name`` 涂蓝会让每一个 Python 变量都变蓝。
#:
#: ``Token.Name.Tag`` 和 ``Token.Comment.Preproc`` 的 ``bright_black`` 就是 chalk 的
#: ``grey``（SGR 90），不是「比黑亮一点的黑」——别照着字面改成 ``black``。
CODE_STYLE_MAP: dict[tuple[str, ...], Style] = {
    Token.Keyword: Style(color="blue"),  # keyword / literal
    Token.Keyword.Type: Style(color="cyan", dim=True),  # type
    Token.Name.Builtin: Style(color="cyan"),  # built_in
    Token.Name.Class: Style(color="blue"),  # class / title.class
    Token.Name.Function: Style(color="yellow"),  # function / title.function
    Token.Name.Tag: Style(color="bright_black"),  # tag
    Token.Name.Attribute: Style(color="cyan"),  # attr
    Token.Name.Namespace: Style(color="blue"),  # name
    Token.Literal.String: Style(color="red"),  # string / regexp
    Token.Literal.Number: Style(color="green"),  # number
    # comment 在 Claude Code 里是**纯绿**，既不斜体也不压暗。
    Token.Comment: Style(color="green"),
    Token.Comment.Preproc: Style(color="bright_black"),  # meta
    Token.Generic.Inserted: Style(color="green"),  # addition
    Token.Generic.Deleted: Style(color="red"),  # deletion
    Token.Generic.Emph: Style(italic=True),  # emphasis
    Token.Generic.Strong: Style(bold=True),  # strong
}

#: 渲染 Markdown 用的 console。**复用同一个实例**——每次构造都要重建主题查找
#: 表，而这里是每 50ms 一次的热路径。宽度不写死，靠 ``options.update_width()``
#: 按次传入。
#:
#: ``color_system="truecolor"`` 必须给：否则 ANSI 具名色会被量化，链接的
#: ``bright_blue`` 到不了 94 号色。
CONSOLE = Console(
    theme=MARKDOWN_THEME,
    color_system="truecolor",
    force_terminal=True,
    legacy_windows=False,
)

#: 代码块配色。不需要 ``background_color``：``ANSISyntaxTheme`` 的背景样式本来就
#: 是空的，代码块不会在正文里糊出一块色板。
TauCodeTheme = ANSISyntaxTheme(CODE_STYLE_MAP)


class _LeftHeading(Heading):
    """一级标题也左对齐。"""

    LEVEL_ALIGN: ClassVar[dict[str, str]] = dict.fromkeys(
        ("h1", "h2", "h3", "h4", "h5", "h6"), "left"
    )


class _TightCodeBlock(CodeBlock):
    """代码块去掉上下各一行的 padding。"""

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        syntax = Syntax(
            str(self.text).rstrip(),
            self.lexer_name,
            theme=self.theme,
            word_wrap=True,
            padding=0,
        )
        yield syntax


class _QuotedBlockQuote(BlockQuote):
    """引用块：``▎`` 压暗，正文斜体。

    等价于 Claude Code 的 ``dim("▎") + " " + italic(整行)``。Rich 出厂是 ``▌``
    且整段只压暗（``markdown.block_quote`` 一个样式同时管符号和正文），分不开。

    符号只挂 ``dim``、**不带** ``self.style``：继承了的话 ``▎`` 会跟着正文一起
    变斜体，而 Claude Code 的 ``dim("▎")`` 是单独一层，只有压暗。
    """

    MARKER: ClassVar[str] = "▎ "

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        render_options = options.update(width=options.max_width - len(self.MARKER))
        lines = console.render_lines(self.elements, render_options, style=self.style)
        marker = Segment(self.MARKER, Style(dim=True))
        for line in lines:
            yield marker
            yield from line
            yield Segment("\n")


class _PlainList(ListItem):
    """列表符号对齐 Claude Code：无序用短横、有序带句点，两个都不上色。

    两处都是 Rich 写死的：``render_bullet`` 里是 ``" • "``，``render_number`` 里
    是「右对齐的数字 + 空格」，没有句点。
    """

    BULLET: ClassVar[str] = "- "
    PADDING: ClassVar[str] = "  "

    def render_bullet(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        render_options = options.update(width=options.max_width - len(self.BULLET))
        lines = console.render_lines(self.elements, render_options, style=self.style)
        bullet_style = console.get_style("markdown.item.bullet", default="none")
        new_line = Segment("\n")
        for first, line in loop_first(lines):
            yield Segment(self.BULLET if first else self.PADDING, bullet_style)
            yield from line
            yield new_line

    def render_number(
        self, console: Console, options: ConsoleOptions, number: int, last_number: int
    ) -> RenderResult:
        # 字段宽 =「最长的编号 + 句点」再留一格给编号和正文之间的空格。
        width = len(f"{last_number}.") + 1
        render_options = options.update(width=options.max_width - width)
        lines = console.render_lines(self.elements, render_options, style=self.style)
        number_style = console.get_style("markdown.item.number", default="none")
        new_line = Segment("\n")
        padding = Segment(" " * width, number_style)
        numeral = Segment(f"{number}.".rjust(width - 1) + " ", number_style)
        for first, line in loop_first(lines):
            yield numeral if first else padding
            yield from line
            yield new_line


class _PlainRule(HorizontalRule):
    """``hr`` 是字面量 ``---``，不是一条铺满整行的横线。"""

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        yield Text("---")


class TauMarkdown(Markdown):
    """左对齐标题、字面量 hr、``▎`` 引用块、``-`` 列表、代码块不铺底色的 Markdown。"""

    elements: ClassVar[dict[str, type]] = {
        **Markdown.elements,
        "heading_open": _LeftHeading,
        "fence": _TightCodeBlock,
        "code_block": _TightCodeBlock,
        # 键名是 ``*_open``，写 ``"blockquote"`` 不会报错，只是永远不生效。
        "blockquote_open": _QuotedBlockQuote,
        "list_item_open": _PlainList,
        "hr": _PlainRule,
    }


def _to_content(renderable: Markdown, width: int) -> Content:
    """Rich 排好版的行 → Textual ``Content``（带 span 样式，因此可框选）。

    ``pad=False``：行尾不补空格。补了的话每个空行都会变成一整行空白，
    选中一片区域时会带出一堆尾随空格。
    """
    lines: Iterable[list[Segment]] = CONSOLE.render_lines(
        renderable, CONSOLE.options.update_width(width), pad=False
    )
    text: list[str] = []
    spans: list[Span] = []
    position = 0
    for index, line in enumerate(lines):
        if index:
            text.append("\n")
            position += 1
        for segment in line:
            text.append(segment.text)
            if segment.style is not None:
                spans.append(
                    Span(
                        position,
                        position + len(segment.text),
                        TuiStyle.from_rich_style(segment.style),
                    )
                )
            position += len(segment.text)

    return Content("".join(text), spans)


def render_markdown(source: str, width: int) -> Content:
    """把累积的 Markdown 源码变成可框选的 ``Content``。

    首尾的换行先摘掉：流式拼接时正文前面常挂着分隔空行，Rich 会老老实实把
    它渲染成一条空行，在对话流里就是一段凭空的空隙。

    ``latex.convert`` 必须在 Rich 之前跑：``rank_i`` 里的下划线一进 Markdown
    就是强调标记，解析完再想还原已经拿不到原始字符了。

    整段只有空白、或宽度还没量出来（挂载首帧是 0）时返回空 ``Content``——
    ``Markdown("")`` 在 Rich 里会渲染出一个零高度对象，``Console`` 宽度为 0
    时折行也没有意义。宽度为 0 不是错误状态：``BodyColumn.on_resize`` 会在
    第一次真实布局时补上。
    """
    trimmed = source.strip("\n")
    if not trimmed.strip() or width <= 0:
        return Content("")

    return _to_content(
        TauMarkdown(
            convert(trimmed),
            code_theme=TauCodeTheme,
            inline_code_theme=TauCodeTheme,
            justify="left",
            hyperlinks=True,
        ),
        width,
    )
