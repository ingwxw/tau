# TUI 中文输入法布局修复

## 改动

- 主聊天输入使用软换行的 `PromptInput(TextArea)`，让 Textual 原生维护终端硬件光标位置。
  早先这里写的是「必须是单行 `Input`」，2026-09-20 为了支持多行输入主动放宽——
  代价是 `Input` 那条「渲染写死 `no_wrap`」的天然保证没了，下面几条约束因此更值得钉住。
- 输入框不再绘制占位文字。macOS 输入法的预编辑串由终端单独绘制，保留占位文字会让两者重叠。
- 输入框使用与主界面相同的黑色背景，并关闭 Textual 聚焦时默认添加的背景 tint。
  macOS 输入法会在硬件光标处绘制预编辑串，额外的实色或聚焦 tint 会把这一行误认为灰色输入行。
- **输入行上下不能出现任何实色带子。** `TextArea` 默认有三处会画带子，全部要关：
  - 光标所在整行（`$boost` 底色）：构造时传 `highlight_cursor_line=False`。
    这个开关**只在构造时有效**——它是没有 watcher 的 reactive，运行中再赋值不会清
    `_line_cache`，带子照旧，别指望 `prompt.highlight_cursor_line = False` 能生效。
  - 光标旁括号的底色：`match_cursor_bracket` 是 `reactive(init=False)` 且同样没有
    watcher，构造签名里没有它，只能靠 CSS（`#prompt .text-area--matching-bracket`）。
  - 光标那一格的底色（来自主题的 `$input-cursor-background`，深色主题下接近纯白）：
    没有开关，在 CSS 里钉成一个明确的块状光标。
- 隐藏输入框的水平和垂直滚动条，避免组合输入期间出现横向灰色滚动区域。
- 提交走 `PromptInput.Submitted`（自定义消息），Enter 绑定**必须带 `priority=True`**。
  详见下面「Enter 为什么必须 priority」。
- 界面改成 Claude Code 单栏风格后，输入框上下两条横线由 `#composer` 容器绘制
  （`border-top` + `border-bottom`，无侧边），`#prompt` 自身仍然没有边框、没有底色。
  **「没有底色」的判据是「和 `Screen` 同底色」，不是「等于黑」**：应用底色是
  `theme.BG`（`#1a1a1f`，冷调深灰），`check_tui_prompt.py` 断言的是前者，
  换 `BG` 时不用去改断言。

## 布局：高度与封顶

高度不写死。`TextArea` 在软换行下把 `virtual_size` 设成
`(0, wrapped_document.height)`，而 `ScrollView.get_content_height()` 直接返回
`virtual_size.height`，所以 `height: auto` 会精确地跟着折行数走，也会精确地缩回去，
一次 `pause()` 就收敛。

上限封在 `#prompt`（`max-height: 10`）而**不是** `#composer`：

> 封在容器上只会把整个 `TextArea` 裁掉。它照样有 43 行高，于是自认为完全可见、
> 根本不滚（`scroll_y` 恒为 0），光标跑出可视区之后就再也看不见了，打字全靠盲打。
> 封在 `#prompt` 上它才会成为滚动主体，光标始终留在框内。

`#composer` 的高度因此是 `1 + 10 + 1 = 12`，且只是「上横线 + 内容 + 下横线」的自然结果。

`overflow-y` 必须是 `auto` 而不是 `hidden`：`hidden` 会让 Textual 直接把垂直滚动
判成不可用，封顶之后看不见的部分就真没了。配合 `scrollbar-size-vertical: 0`
做到「能滚但不画条」；条宽为 0 同时也断掉了「滚动条出现 → 折行宽度变化 → 重新折行」这个回环。

## Enter 为什么必须 priority

同一个「回车提交」，两个组件的机制不一样：

- `Input` 用普通（非 priority）的 `Binding("enter", "submit")` 就行。`Input._on_key`
  只对 `event.is_printable` 调 `event.stop()`，Enter 不可打印，事件能冒泡到
  `App._on_key`——非 priority 的绑定只在那条路径上被查。
- `TextArea._on_key` 会把 Enter 换成 `"\n"` 并 `event.stop()`，事件根本冒不到
  `App._on_key`。所以**非 priority 的 Enter 绑定是死代码**，写上去不会报错，只是永远不触发。

唯一的挂钩点在 `App.on_event` 里的 `_check_bindings(event.key, priority=True)`，
它在转发给聚焦组件之前执行。三个键（`enter` / `shift+enter` / `ctrl+j`）统一写
`priority=True`。

**副作用**：`Ctrl+J` 在不支持 kitty 键盘协议的终端里发的是 `\n`，会被 Textual 认成
`enter`，于是变成「提交」而不是「换行」。Ghostty 等支持 kitty 协议的终端没有这个问题。

## 剪切键：`ctrl+x` 会吃掉草稿

`Input.action_cut` 在无选区时是空操作，`TextArea.action_cut` 则会**删掉整行**。
提示行明写着「ctrl+x 中断」，直接换过去会让想中断的人把草稿整行删掉。
`PromptInput` 覆写了 `action_cut`，只在真有选区时才剪切，对齐 `Input` 的语义。

忙碌时 `ctrl+x` 也仍然正常中断，但**不再是靠 disable 输入框做到的**（2026-09-20 改）。
早先 `_set_busy` 会 `prompt.disabled = True`，`Widget.watch_disabled` 里的
`screen.focused.blur()` 让绑定链回落到 `[Screen, App]`。现在忙碌期间要能继续打字排队，
焦点必须留在输入框里，那条路走不通了——改由 `PromptInput.action_cut` 自己转交：

```python
if getattr(app, "is_busy", False):
    app.action_cancel()
    return
```

**`_set_busy` 里不能再出现 `prompt.disabled`。** 焦点就是硬件光标，失焦等于中文打不进去，
这是输入法的硬约束而不是可以随手改回来的实现细节。`check_tui_input.py` 在忙碌中途
断言 `not prompt.disabled` 和 `app.focused is prompt`，盯的就是这条。

## 中文一长就变成 `^[49;;…u`：Textual 的转义序列搜索上限

**症状**：用输入法打中文，组合到**第 5 个字**输入框里就冒出
`^[[49;;25645:24314:38463:25289:…u` 这样的字面乱码，前面几个字正常。

**根因在 Textual，不在终端也不在布局。** kitty 键盘协议的「关联文本」报告形如
`CSI 49 ; <修饰键> ; <码点表> u`，输入法组合期间终端会连着发好几条，每条带上
当前整段预编辑串。Textual 8.2.8 明确请求了这个能力
（`drivers/linux_driver.py:290` 的 `KITTY_REPORT_ASSOCIATED_TEXT`），也**完整实现了**
它的解析（`_xterm_parser.py:372` 取第三个分号段当字符）。问题出在解析之前那道闸门：

```python
_MAX_SEQUENCE_SEARCH_THRESHOLD = 32   # _xterm_parser.py:20
```

序列攒到 33 个字符还没被认出来，就被当成「不认识的转义序列」整个放弃，
改用 `reissue_sequence_as_keys` 把原始字节**逐个重发成按键**
（`_xterm_parser.py:256`），ESC 在那条路径上被换成 `^`——于是整串原样打进输入框。

换算一下就知道为什么偏偏是第 5 个字：序列总长 `6n + 6`（每个汉字 5 位码点 + 1 个
冒号 = 6 字符，`\x1b[49;;` 前缀 6 个，末尾 `u` 1 个）。

| 组合字数 | 序列长 | 结果 |
|---|---|---|
| 1–4 | 12–30 | ≤ 32，正常解析出汉字 |
| 5+ | 36+ | > 32，整串变成 `^[49;;…u` |

**修法**：`src/tau_coding/tui/kitty_text.py` 的 `widen_sequence_search()` 把上限抬到
1024（够 169 个汉字），在 `TauTuiApp.__init__` 里调——必须在 `run()` 之前，
驱动线程一起来就开始解析终端输入了。只升不降，幂等。
正则本身匹配任意长的码点表，抬上去之后长串跟短串一样被正确解出来，
**汉字是真的还回来了，而不是被丢掉**。

**这不是换 `TextArea` 引入的回归。** 实测（`/tmp` 探针，可复现）：把同一串按键喂给
旧的 `Input`，`value` 得到的是**逐字节相同**的乱码。乱码在 `XTermParser` 里就产生了，
早于任何 widget；`Input._on_key` 和 `TextArea._on_key` 都无差别地插入可打印字符。

**不要改用 `TEXTUAL_DISABLE_KITTY_KEY`。** 整体关掉 kitty 协议会让 `shift+enter`
退化成 `enter`、`ctrl+j` 退化成回车提交，正好废掉刚做的多行输入。

上游至今没修（PyPI 上 8.2.8 已是最新版）。上游修好之后
`kitty_text.py` 整个模块可以直接删掉——`check_tui_prompt.py` 里的断言盯的是
**解出来的字符**而不是那个常量，删掉后照样通过。

## 两个容易踩的尺寸细节

- `wrap_width = 内容宽 - 1`（给行尾光标留一格）。20 格的框里 CJK 一行只放得下 9 个字，
  不是 10 个。
- `tab_behavior` 保持 `"focus"`。设成 `"indent"` 会让 `TextArea._on_key` 连 `escape`
  一起吞掉，App 的取消就没了。

## 助手正文的 Markdown 渲染

`src/tau_coding/tui/markdown.py` 只做「源码 → **`textual.content.Content`**」这一件事，
节流在 `widgets.MarkedRow` 里。分开是因为两者的成本完全不同：`Markdown` 每次构造都要重解析
整篇，实测 1KB 1.9ms / 4KB 5.3ms / 16KB 21ms，按 delta 逐字重解析会把一核跑满；
而「什么时候重解析」是控件的状态问题，跟 Markdown 怎么渲染无关。

**出口必须是 `Content`，不能返回 Rich 对象。** 这一条不是风格偏好：
`textual/visual.py` 的 `visualize()` 会把任何 Rich 可渲染对象包成 `RichVisual`，而
`RichVisual.render_strips` 直接 `Strip(line)` 包装，**不带 `style._meta["offset"]`**。
`Compositor.get_widget_and_offset_at` 靠这个 meta 找到内容控件，找不到就退化成容器级
选区——鼠标拖过去选不中任何东西，`ctrl+c` 也复制不出内容（详见下面「框选与复制」）。
`Content` 是 Textual 唯一可选的渲染结果，`Static` 持 `str` / `Text` 时走的正是它，
所以用户消息和工具输出一直是好的，这个问题只藏在助手回复里。

所以流程是「Rich 负责解析和排版 → 拆成 segment → 拼回 `Content`」：`_to_content()`
把 `Console.render_lines(..., pad=False)` 的结果逐段拼起来，每段配一个
`Span(pos, pos + len(text), Style.from_rich_style(seg.style))`。几个不能省的细节：

- **宽度要用 `options.update_width(width)` 按次传**，不能给 Console 写死，也不要在每次
  渲染时新建 Console（会重建主题查找表）。
- **`color_system="truecolor"`**：否则链接的 `bright_blue` 会被量化，到不了 94 号色；
  `Color.from_rich_color` 拿到的也已经不是原色。
- **`pad=False`**：补了行尾空格的话，选中一片区域会带出一堆尾随空格。
- `Style.from_rich_style` 保留 `link`，所以 `hyperlinks=True` 的超链接不会丢。

**配色照 Claude Code 2.1.276 的 Markdown 渲染器（二进制里的 `JT`）和它的 highlight.js
scope 表逐条抄的**，不是自己挑的。三条要点：

- **代码块的字色是 ANSI 具名色，不是十六进制。** Claude Code 用的是 chalk 的 `blue` /
  `cyan` / `green` / `red` / `yellow` / `grey`，也就是 `ESC[34m` / `36` / `32` / `31` /
  `33` / `90`——颜色由**用户自己的终端调色板**决定，它根本没有 RGB 配色表。这一点顺带
  解决了「代码块是霓虹色」：早先照搬的 pygments monokai 是六个固定真彩色（`#ff4689`
  关键字、`#66d9ef` 函数、`#a6e22e` 数字），在任何终端上都一样扎眼。实现上必须走
  `ANSISyntaxTheme`——`PygmentsSyntaxTheme.get_style_for_token` 内部写死 `color="#" + color`，
  只吃十六进制，给不了 ANSI 具名色；而 `Syntax.get_theme()` 对 `SyntaxTheme` 实例是原样
  返回的，`Markdown(code_theme=...)` 一路透传，所以换得掉。**别给 `Token.Name` 上色**：
  hljs 的 `variable` / `params` 都不上色，涂蓝会让每一个 Python 变量都变蓝。
- **标题不带颜色。** h1 是 `bold + italic + underline`，h2 及以下是 `bold`，分级靠字重不靠
  色相。链接是 `bright_blue`（chalk 的 `blueBright`，SGR 94）且**没有下划线**——注意
  `markdown.link_url` 也得设，Rich 真正拿去着色的其实是它，只改 `markdown.link` 不生效。
- **符号不上色。** 引用块是「`▎` 压暗 + 正文斜体」，列表符号是 `-` 和 `1.`，`hr` 是字面量
  `---`。整篇只有行内代码和链接是有色的：行内代码是主题键 `permission`（`#b1b9f9`），
  **只有字色、没有底色**——`markdown.code` 给的就是字色，它不是一块浅色芯片（本项目早先
  的注释是这么写的，是错的）。

**主题必须挂在 Console 上，不能用 Rich 的 `DEFAULT_STYLES`。** Rich 的 `Markdown` 用
`console.get_style("markdown.h2")` 这类查找解析元素样式，**跟 `code_theme` 无关**；不给
console 挂主题就会拿到出厂值：`underline magenta`（h2）、`magenta`（block_quote）、
`cyan`（item.number / table.border / list）、`bold`（item.bullet）。`check_tui_render.py`
的配色断言是个**闭集**：正文里出现的每个前景色都必须落在
`ansi_{blue,cyan,green,red,yellow,bright_black,bright_blue}` 加 `#b1b9f9` 里——出界的只可能
来自 `DEFAULT_STYLES` 回退或 pygments 真彩色漏进来。

**数学公式要在进 Rich 之前转。** 助手爱写 `$$...$$`，而终端没有 MathJax。
`latex.convert()`（`src/tau_coding/tui/latex.py`，纯函数）把 LaTeX 换成 Unicode，在
`render_markdown()` 里、构造 `TauMarkdown` **之前**调用。顺序不能反——`rank_i` 的下划线一进
Markdown 就是强调标记，两个 `_` 配成对之后整段变斜体，那时再想还原已经拿不到原始字符了。
这是 **Tau 自己的增强**：Claude Code 的 `JT` 里没有数学分支，它把 `$$...$$` 原样打出来。
围栏代码块和行内代码原样保留，半截的 `$$...` 原样留下不报错，认不出的行内 `$` 只跳过它
自己、后面照转（早先那次实现会就此掐断整篇的扫描，屏幕上一整段 `$...$` 原样显示）。

**宽度是渲染输入，所以正文列改成按需渲染。** `widgets.BodyColumn` 不把渲染结果存成
`Static` 的内容，而是在 Textual 来问的时候才算：`get_content_height()` 用它给的宽度渲染，
`render()` 用自己实际的宽度渲染，两个答案永远出自同一个宽度。**不要改回
「`on_resize` 里 `update()`」**——从 resize 处理器里再申请一次布局会被 Textual 合并掉：
`Widget.refresh` 只在 `_layout_required` 由假转真时自增 `_layout_updates`，已经是真就
不再计数，而布局请求是记账消费的，被并掉的那次不会补发。结果是正文永远停在**高 1 行**
（内容其实渲染好了，只是被 `overflow: hidden` 裁掉），`region.height` 再也不动，且不报
任何错。这个 bug 是间歇的（取决于 resize 和布局谁先到），实测 60 次里中 2 次——
`check_tui_copy.py` 里「渲染行数必须等于控件高度」那条断言就是盯它的。

节流的形状：收到增量先置脏，`set_timer(0.05, flush)` 只挂一次；遇到 `\n` 立即 flush，
因为换行是块边界，晚一拍就会看到「半截的列表项」。`body_text` 始终返回**原始源码**，
它才是流式拼接的唯一真相，也是渲染的输入——断言全部盯它，不盯渲染结果。

**`TauMarkdown` 改 Rich 的五处默认表现**，都靠 `Markdown.elements` 这个类变量替换负责的
Element 类。**键名是 `blockquote_open` / `list_item_open` 这种 `*_open` 形式，写成
`"blockquote"` 不会报错，只是永远不生效**：

- **标题不居中。** Rich 的 `Heading.LEVEL_ALIGN` 把 h1 定成居中，在跟着气泡宽度变化的
  对话流里会左右横跳。
- **代码块不铺底色、不留上下空行。** 底色来自 pygments 主题的 `background_color`
  （monokai 是 `#272822`），会在底色上糊出一块色板；上下各一行 padding 又让每个代码块
  前后空两行。`ANSISyntaxTheme` 的背景样式本来就是空的，`padding=0` 去掉空行。
- **引用块用 `▎` 且正文斜体**（Rich 写死 `▌`，且整段只压暗不变斜体）。符号只挂 `dim`、
  不带 `self.style`，否则 `▎` 会跟着正文一起变斜体，而 Claude Code 的 `dim("▎")` 是单独
  一层。
- **列表符号是 `-` 和 `1.`**（Rich 写死 `" • "`，有序列表还不带句点）。
- **`hr` 是字面量 `---`**（Rich 画一条铺满整行的 `─────`）。

## 框选与复制

两条独立的毛病，缺一条都复制不出东西：

1. **选区锚不上。** 见上面「出口必须是 `Content`」。
2. **`ctrl+c` 被抢走。** App 上那条 `interrupt` 是 `priority=True` 的绑定，会遮蔽
   `Screen.BINDINGS` 里的 `Binding("ctrl+c,super+c", "screen.copy_text")`。让位只能靠
   `TauTuiApp.check_action` 返回假——它返回假时 `App.run_action` 也返回假，绑定链继续
   往下走。现在让的是两种选区：输入框里的（归 `TextArea`）和对话流里的
   （`screen.get_selected_text()` 非空）。

**但只能在真有选区时让。** `Screen.action_copy_text` 在无选区时 `raise SkipAction()`，
无条件让位会让空选区下的 `ctrl+c` 一路跳过，**连退出都一起废掉**——按多少次都退不出去，
而且不报任何错。`check_tui_copy.py` 的两条检查一头一尾钉住这件事：有选区时复制、无选区时
照旧双按退出。

`screen.get_selected_text()` 无选区时是 O(1)（`if not self.selections: return None`），
放在 `check_action` 里不心疼。

**别在拖拽之后动输入框。** `TextArea` 的选区一变就会 `app.clear_selection()`
（`widgets/_text_area.py`，Textual 的设计：动了输入框就不再是「选中屏幕上那一段」的
语境）。所以「选中 → 打字 → ctrl+c」这个顺序下复制是不生效的，那是 Textual 的既定行为，
不是 bug；写检查时草稿必须在拖拽**之前**设好。

选区配色在 `app.py` 的 CSS 里：底色换成本项目的 `$tau-subtle`（默认是主题的亮蓝，
在深色底上很扎眼），`color: transparent` 显式钉住——换成具体颜色会把选区里的语法色整片
刷掉。

## 忙碌、排队与命令面板

**排队必须在同一条 worker 里抽干。** `_run_prompt` 是 `@work(group="agent",
exclusive=True)`，在它自己的 `finally` 或回合结束时再 `call_later(self._run_prompt, ...)`
会撞上「exclusive 取消同组正在运行的 worker」——也就是它自己。所以队列由同一个循环
`while True: _run_turn() → pop` 顺序消费。

出队时必须补挂 `UserMessage`：提交那一刻正忙，`submit_prompt` 只做了入队，气泡还没画。

**命令面板的上下键是 priority 绑定 + `check_action` 开合。** `check_action` 返回假时
`App.run_action` 返回假、绑定链继续往下走——所以关掉一个绑定等于把它**让给**下层控件，
而不是让它失效。`up`/`down`/`tab` 平时让给 `TextArea`（光标移动、插入缩进），只有面板
开着时才被 App 接管。同理 `ctrl+c`：输入框里有选区时让它落回 `TextArea` 的复制。

**`ctrl+c` 退出要按两次**，靠 `_quit_armed_at` + `QUIT_CONFIRM_WINDOW` 计时。
这里踩过一个坑：`action_interrupt` 在调 `_confirm_quit()` 之前如果先把 `_quit_armed_at`
清成 `None`，第二次按下就永远看到「没武装过」，只会重新武装——键按多少次都退不出去，
而且不报任何错。武装与解除都在 `_confirm_quit` / `_disarm_quit` 里，调用方不要插手。

## 未读提示与跟随底部

「跟不跟随」不能靠监听滚轮事件维护：键盘、拖滚动条、`scroll_end` 都会改 `scroll_y`，
只认一种输入源迟早跟真实位置脱节。`MessageList.watch_scroll_y` 是这些路径的公共汇合点。

`follow` 是**缓存的意图**，不是当场算出来的位置——内容变长只抬高 `max_scroll_y` 而不动
`scroll_y`，直接比 `is_vertical_scroll_end` 会把「跟着底部时来了新内容」误判成离开底部。
维持它的是 `TauTuiApp._after_content`：跟随时就 `scroll_end()` 把视图压到底部。

因此**内容必须走 `_mount` 进去**。绕过 `_after_content` 直接往 `#messages` 上 mount，
会造出「`follow` 为真、视图却停在顶部」这个界面上不存在的状态，跟着的滚动检查就会
以一种很难看懂的方式失败（`scroll_up` 被 clamp 在 0，什么都不发生）。`check_tui_input.py`
因此是提交输入走真实回合产出，而不是直接 mount。

## 边界

macOS 输入法候选词窗口由终端负责绘制，项目本身无法在无头测试中生成候选词列表。因此自动检查验证的是项目能否在中文文本和窄终端下稳定布局；候选词窗口的最终视觉效果仍需在本机终端输入拼音确认。

## 终端兼容性：这不是本项目能修的

2026-09-20 实测，同一个界面、同一套输入法：

| 终端 | 中文输入 | 原因 |
|---|---|---|
| **Ghostty** | 正常 | 在 AppKit 层用 `markedText` 接管 preedit，组合期间不往网格里写东西，组合完才一次性把文本发给程序 |
| **Apple Terminal** | 整个界面错乱 | 把 preedit 内联画进终端网格，且已知在光标处于 pending-wrap 列时画错位置 |
| **VS Code / Cursor 集成终端** | 错乱 | xterm.js 的 `CompositionHelper` 把 `.composition-view` 叠在网格上；上游还挂着中文相关的 [#5023](https://github.com/xtermjs/xterm.js/issues/5023)、[#9695](https://github.com/microsoft/vscode/issues/9695) |

Apple Terminal 这一条是**终端自己的缺陷**，不是本项目的布局问题。旁证有三条，都能复现：

1. 同样的错乱在**纯 zsh 提示符下、不跑任何 TUI 程序**时也会出现；
2. 送到程序的**字节流是完全正确的**，错的是终端自己画出来的那几行——所以按 Enter 触发一次全量重绘，画面就干净了；
3. Textual 每帧都会把硬件光标移到 caret 上（`app.py` 的 `Control.move_to`），本项目实测光标停在 `(5, 19)`，正好是输入行的字符位置。锚点是对的，不存在 Claude Code 当初那种「藏了真光标、组合串被甩到屏幕左下角」的问题（[claude-code#39245](https://github.com/anthropics/claude-code/issues/39245)）。

**结论：推荐 Ghostty。** 换终端是唯一确定有效的办法，换任何支持 kitty 键盘协议、把 preedit 当浮层处理的终端都行（Ghostty / kitty / WezTerm / iTerm2）。

## 检查

```bash
cd /Users/wxw/Desktop/tau重写

# 输入法约束 + 布局契约 + 软换行增长/封顶/光标可见性（20 / 40 / 110 三种宽度）
# + 长关联文本不被当成字面乱码
PYTHONPATH=src uv run python examples/check_tui_prompt.py

# 数学公式：LaTeX → Unicode，代码块与流式半截输入不受影响
PYTHONPATH=src uv run python examples/check_tui_math.py

# 对话流渲染：标记符号、Markdown 字形/字重/配色闭集、工具块、spinner、横幅降级
PYTHONPATH=src uv run python examples/check_tui_render.py

# 流式时序与行高：静默期的活动指示、工具执行中 spinner 的位置、折行行高
PYTHONPATH=src uv run python examples/check_tui_stream.py

# 输入区交互：命令面板、忙碌排队、ctrl+c 双按、未读与跟随
PYTHONPATH=src uv run python examples/check_tui_input.py

# 框选与复制：助手正文选得中、ctrl+c 复制得走、宽度变了行数还对得上
PYTHONPATH=src uv run python examples/check_tui_copy.py
```

`check_tui_stream.py` 盯的是一个静默失败模式：`.tool-head` / `.tool-result` 这两行
没有在 CSS 里写 `height: auto`，完全依赖容器的默认值——`HorizontalGroup` 是 `auto`，
`Horizontal` 是 `1fr`。基类换错时不会报错，多出来的高度被 `overflow: hidden` 裁掉，
只是看起来「中间空了一大片」。所以那里的断言是逐行比对行高和正文列高度，不是看截图。

`check_tui_prompt.py` 同理，另外钉住三条不看截图就会漏掉的：

- **长一点的组合串不能被当成字面按键。** `kitty_text.widen_sequence_search()` 那道
  补丁一旦失效（上游改了内部实现、或有人把它从 `TauTuiApp.__init__` 里删掉），
  界面照样能跑、短中文照样正常，只有第 5 个字以后开始出乱码。所以检查里喂一条
  12 字的关联文本，先断言解析出的字符，再喂给 `#prompt` 断言落框后的 `text`。

- **光标必须留在输入框可视区内。** 上面「封顶封在 `#prompt` 而不是容器上」那条，
  如果封错了地方，几何断言（高 12）照样过，但光标会跑到框外——所以断言的是
  `cursor_screen_offset` 落在 `#prompt` 的 region 里，且 `scroll_offset.y > 0`。
- **`ctrl+x` 不能吃掉草稿。** 覆写很容易被后来的人当成多余代码删掉，所以两头都钉：
  没选中时文本不变，真选中了仍然要能切走。

`check_tui_input.py` 盯的是「按下去没反应但也不报错」的那一类：面板要靠
`TextArea.Changed` 才会弹，队列要在同一个 worker 里抽干，`ctrl+c` 得绕开 `TextArea`
的复制绑定。任何一处接错线，界面照样跑，只是那几个键静默失效。最前面一条是
**忙碌时焦点必须仍在 `#prompt` 上**——它比排队功能本身重要。

`check_tui_copy.py` 盯的是「界面照样跑，只是鼠标拖过去什么都没选中」这一类。最前面一条
是助手正文的出口必须是 `Content`——它退回成 Rich 对象时渲染一模一样，只有拖拽会失效。
另外两条只在特定条件下才露头：**渲染行数 ≠ 控件高度**（按需渲染那条注释里写的合并布局
竞态，正文会被裁成一行）和**空选区下的 `ctrl+c`**（`check_action` 若写成无条件让位，
退出会静默失效）。

另有一条不属于界面：**取消是协作式的**。`run_agent_loop` 只在事件之间查一次 token，
所以一个「先 `sleep` 再吐字」的 provider 会让 `ctrl+c` 看起来像失灵，实际是循环压根
没回到判断点。真实 provider 每收到一个 chunk 就回一次循环，取消是立刻生效的；
写这类检查时 provider 的形状要照着真实的来（字与字之间留间隔），别用「先愣住一会儿」。
