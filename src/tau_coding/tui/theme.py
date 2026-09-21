"""配色与版本常量。

调色板对照 Claude Code 官方主题色标命名（claude / inactive / subtle /
promptBorder / permission / success / error），统一加 ``tau-`` 前缀，避免与
Textual 内置变量（``$text`` / ``$background`` / ``$error`` …）冲突。

``PALETTE`` 由 ``TauTuiApp.get_css_variables()`` 注入，CSS 里写 ``$tau-claude``；
需要直接构造 Rich ``Text`` 样式的地方，用下面同名的 Python 常量。

**这里的取值与 Claude Code 的官方值不完全相同，是有意的。** Claude Code 从不
画应用底色（``Screen`` 透出终端自己的背景），所以它的 ``text`` / ``inactive`` /
``subtle`` 是照着终端原生底色挑的。Tau 画一块 ``BG``，这几个值就是照着这块
底色挑的：同一个色系、明度关系（正文 > 次级 > 符号）保持一致，具体色值不同。
换 ``BG`` 时要连带复核下面几个常量，别只改一个。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

#: 品牌强调色：logo、spinner。
CLAUDE = "#d97757"

#: spinner 渐变的亮部，对应官方的 <token>Shimmer 配对色。
CLAUDE_SHIMMER = "#f0a58c"

TEXT = "#e4e4e7"
INACTIVE = "#7c7c85"
SUBTLE = "#3f3f46"
ERROR = "#ff6b6b"
PROMPT_BORDER = "#5a5a63"

#: 行内代码。对应 Claude Code 主题键 ``permission`` 的暗色值 ``rgb(177,185,249)``。
#: 这是 Claude Code 唯一一处给普通 Markdown 元素上的彩色（``JT`` 里 ``codespan``
#: 那条），照抄它比自己挑一个更省事，也真的对得上。
PERMISSION = "#b1b9f9"

#: 应用底色。不是纯黑：冷调深灰，和 ``TEXT`` / ``SUBTLE`` 同色系。
BG = "#1a1a1f"

PALETTE: dict[str, str] = {
    "tau-claude": CLAUDE,
    "tau-claude-shimmer": CLAUDE_SHIMMER,
    "tau-text": TEXT,
    "tau-inactive": INACTIVE,
    "tau-subtle": SUBTLE,
    "tau-error": ERROR,
    "tau-prompt-border": PROMPT_BORDER,
    "tau-permission": PERMISSION,
    "tau-bg": BG,
}


def _detect_version() -> str:
    """读取已安装包版本；``PYTHONPATH=src`` 直接跑时回退到 pyproject 的值。"""
    try:
        return version("tau-ai")
    except PackageNotFoundError:
        return "0.1.0"


APP_VERSION = _detect_version()
