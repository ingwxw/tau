"""绕开 Textual 对超长转义序列的搜索上限。

kitty 键盘协议的「关联文本」报告形如 ``CSI 49 ; <修饰键> ; <码点表> u``，
输入法组合中文的过程中终端会连着发好几条，每条带上当前整段预编辑串。
Textual 8.2.8 明确请求了这个能力（``drivers/linux_driver.py:290`` 的
``KITTY_REPORT_ASSOCIATED_TEXT``），也完整实现了它的解析
（``_xterm_parser.py:372`` 取第三个分号段当字符），但解析之前横着一道闸门：

    _MAX_SEQUENCE_SEARCH_THRESHOLD = 32

序列攒到 33 个字符还没被认出来，就被当成「不认识的转义序列」整个放弃，
改成把原始字节逐个重发成按键（``_xterm_parser.py:256`` 与
``reissue_sequence_as_keys``）。ESC 在那条路径上会被换成 ``^``。

序列总长是 ``6n + 6``：码点表每多一个汉字多 6 个字符（5 位码点 + 1 个冒号），
``\\x1b[49;;`` 前缀占 6 个，末尾 ``u`` 占 1 个。于是**组合到第 5 个汉字就必然
越线**：4 个汉字 30 字符正常，第 5 个一到 36 字符，整串
``^[49;;25105:24590:20040:30693:36947u`` 就原样打进输入框——
「中文稍微一长就显示错误」说的就是这个。

正规做法是把上限抬高。正则本身匹配任意长的码点表，短序列一直是对的，
坏的只是这道闸门；抬上去之后长组合串会像短的一样被正确解出来，
汉字是真的还回来了，而不是被丢掉。

**不要改用 ``TEXTUAL_DISABLE_KITTY_KEY``。** 整体关掉 kitty 协议会让
``shift+enter`` 退化成 ``enter``、``ctrl+j`` 退化成回车提交，
正好废掉多行输入要的那两个键。

上游尚未修复（PyPI 上 8.2.8 已是最新版）。``examples/check_tui_prompt.py``
里的行为检查在补丁失效时会当场失败，上游修好之后这个模块可以直接删掉。
"""

from __future__ import annotations

from textual import _xterm_parser

#: 转义序列的最长搜索长度。够放下 169 个汉字的关联文本，
#: 同时仍远小于任何现实中的异常输入。
SEQUENCE_SEARCH_LIMIT = 1024


def widen_sequence_search() -> None:
    """把 Textual 的转义序列搜索上限抬到 :data:`SEQUENCE_SEARCH_LIMIT`。

    只升不降，将来 Textual 把上限调得比这里更高时不回退。
    幂等，重复调用无副作用。
    """
    current = getattr(_xterm_parser, "_MAX_SEQUENCE_SEARCH_THRESHOLD", None)
    # 常量没了说明上游改了实现，这里补不了——不要静默兜底，
    # 让 examples/check_tui_prompt.py 里的行为检查去报错。
    if isinstance(current, int) and current < SEQUENCE_SEARCH_LIMIT:
        _xterm_parser._MAX_SEQUENCE_SEARCH_THRESHOLD = SEQUENCE_SEARCH_LIMIT
