"""把 Markdown 源码里的 LaTeX 数学换成终端读得懂的 Unicode。

助手很爱用 ``$$...$$`` 写公式，而终端里没有 MathJax：原样显示就是一串
``\\sum_{i} \\frac{1}{k + \\text{rank}_i(d)}``。这里在**交给 Rich 之前**把源码
里的数学转成 Unicode（``∑ᵢ 1/(k + rankᵢ(d))``），剩下的排版交给 Markdown。

必须在源码层做，不能等 Rich 解析完再改：``rank_i`` 里的下划线一旦进了
Markdown 就是强调标记，两个 ``_`` 配对之后整段会变成斜体，那时候再想还原
已经拿不到原始字符了。

**这是 Tau 自己的增强，不是对齐 Claude Code。** Claude Code 的 ``JT`` 里没有
任何数学分支，它把 ``$$...$$`` 原样打出来。

三道边界，都有检查脚本钉着：

- **代码不动。** 围栏代码块和行内代码里的 ``$`` / ``\\frac`` 是代码，原样保留。
- **流式安全。** 半截送进来的 ``$$...``（还没等到闭合）原样留下——正在流进来的
  公式不能报错，也不能把后面的字吞掉。
- **看错了宁可不转，但只不转它自己。** 行内 ``$...$`` 只在内容里带 ``\\`` / ``^`` /
  ``_`` 时才认，否则「价格是 $5 到 $10」会被当成一段公式。认错一个不能连累后面：
  正文里出现一个孤立的 ``$`` 之后，剩下的公式照样要转换。

完整的 LaTeX 不是目标：认识的是模型写公式时最常用的那一小撮命令，不认识的就
去掉反斜杠保留名字（``\\foo`` → ``foo``），绝不吞字。
"""

from __future__ import annotations

import re
from collections.abc import Iterator

__all__ = ["convert"]

#: 命令名 → 符号。希腊字母、运算符、关系符、箭头、括号、省略号。
SYMBOLS: dict[str, str] = {
    # 希腊字母
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ",
    "Omega": "Ω",
    # 运算符
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "propto": "∝", "sim": "∼",
    "infty": "∞", "partial": "∂", "nabla": "∇", "int": "∫", "oint": "∮",
    "sum": "∑", "prod": "∏", "sqrt": "√",
    # 集合与逻辑
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅", "setminus": "∖",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    # 箭头
    "rightarrow": "→", "to": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "mapsto": "↦",
    # 括号与省略号
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋",
    # 竖线：``\mid`` 几乎只出现在集合构造里（``\{x \mid x > 0\}``），
    # 落到「去反斜杠留名字」那条兜底路径上会读成 ``mid``。
    "mid": "|", "vert": "|", "Vert": "‖",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    # 杂项
    "star": "⋆", "ast": "∗", "circ": "∘", "bullet": "•", "prime": "′",
    "angle": "∠", "perp": "⊥", "parallel": "∥", "therefore": "∴",
    "because": "∵", "degree": "°", "surd": "√", "checkmark": "✓",
}

#: 黑板体。``\mathbb{R}`` 这类，逐字符映射，认不出的保留原字母。
BLACKBOARD: dict[str, str] = {
    "R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ",
    "P": "ℙ", "H": "ℍ", "F": "𝔽", "E": "𝔼",
}

#: 上标。**不是**全字母表：Unicode 只给了这些。
SUP: dict[str, str] = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽",
    ")": "⁾", "n": "ⁿ", "i": "ⁱ", "x": "ˣ", "y": "ʸ", "a": "ᵃ", "b": "ᵇ",
    "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "k": "ᵏ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ",
    "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "z": "ᶻ",
    "j": "ʲ", "h": "ʰ", "l": "ˡ", "g": "ᵍ",
    "T": "ᵀ", "A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ", "M": "ᴹ", "N": "ᴺ",
    "P": "ᴾ", "R": "ᴿ",
}

#: 下标。比上标还少，缺的那些走 ``_x`` 回退。
SUB: dict[str, str] = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍",
    ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ",
    "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}

#: 组合附加符。``\hat{x}`` → ``x̂``。只在单字符参数上套，多字符上套会错位。
ACCENT: dict[str, str] = {
    "hat": "̂", "bar": "̄", "tilde": "̃", "dot": "̇",
    "vec": "⃗", "check": "̌", "breve": "̆", "acute": "́",
    "grave": "̀",
}

#: 只吃参数、自己不留痕迹的命令。
DROP = {"left", "right", "displaystyle", "limits", "nolimits", "mathstrut"}

#: 取参数内容、按原样（不再转义）输出的命令。
LITERAL = {"text", "mathrm", "operatorname", "mathsf", "mathtt", "mbox"}

#: 取参数内容、内容仍当数学转的命令。
WRAP = {"mathbf", "mathit", "boldsymbol", "bm", "mathcal", "mathfrak"}

#: 命令形式与字符形式的空白。
SPACE = {r"\,", r"\;", r"\:", r"\ ", r"\quad", r"\qquad"}
TIGHT = {r"\!"}

#: 转义过的字面字符：``\{`` → ``{``。
ESCAPED = {r"\{", r"\}", r"\$", r"\%", r"\&", r"\#", r"\_"}

#: 行内 ``$…$`` 的识别门槛之一：带反斜杠、上标或下标。
_INLINE_MATH_HINT = re.compile(r"[\\^_]")

#: 门槛之二：单个 ASCII 字母。``$k$`` / ``$n$`` 这种行内变量模型写得极多，光靠
#: 上面那条会漏掉一整段。**只认单个字母**——金额后面跟的总是数字，
#: 「价格是 $5 到 $10」因此仍然不会两个 ``$`` 一连就被当成公式。
_INLINE_MATH_LETTER = re.compile(r"[A-Za-z]\Z")

_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
_TICKS = re.compile(r"`+")
#: 朴素扫描的加速闸：一次跳到下一个可能有意义的字符。
_INTERESTING = re.compile(r"[`$\n]")


def _group(source: str, index: int) -> tuple[str, int]:
    """从 ``source[index] == '{'`` 起取配平的组内容，返回 (内容, 新下标)。"""
    depth = 0
    start = index
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
        index += 1
    # 没闭合（流式输入里很常见）：剩下的全算组内，不报错。
    return source[start + 1 :], len(source)


def _bracket(source: str, index: int) -> tuple[str, int]:
    """``\\sqrt[3]{x}`` 里的那个可选参数。"""
    depth = 0
    start = index
    while index < len(source):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
        index += 1
    return source[start + 1 :], len(source)


def _argument(source: str, index: int) -> tuple[str, int]:
    """读一个参数：``{...}`` 组，或单个 token（``\\cmd`` 或一个字）。"""
    while index < len(source) and source[index] == " ":
        index += 1
    if index >= len(source):
        return "", index
    if source[index] == "{":
        return _group(source, index)
    if source[index] == "\\":
        match = re.match(r"\\[A-Za-z]+", source[index:])
        if match:
            return match.group(0), index + len(match.group(0))
        return source[index : index + 2], index + 2
    return source[index], index + 1


def _script(text: str, table: dict[str, str]) -> str | None:
    """整串都能映射才返回，否则返回 ``None``（半截映射比不映射更难读）。"""
    if not text or any(ch not in table for ch in text):
        return None
    return "".join(table[ch] for ch in text)


def _needs_parens(text: str) -> bool:
    """``\\frac`` 的分子分母要不要加括号。

    逐边判断：``\\frac{1}{k + r_i(d)}`` 该出 ``1/(k + rᵢ(d))``，不是
    ``(1)/(k + rᵢ(d))``——多一对括号在终端里就是多两个字符的噪声。
    """
    stripped = text.strip()
    if len(stripped) <= 1:
        return False
    return " " in stripped or any(op in stripped for op in "+-=<>±∓×÷")


def _escape_underscores(text: str) -> str:
    """裸下划线必须转义：``W_q 和 X_q`` 里的两个会被 Markdown 配成一对，整段变斜体。

    ``^`` 不是 Markdown 的标记，不用管。
    """
    return text.replace("_", r"\_")


def _script_or_fallback(marker: str, plain: str, table: dict[str, str]) -> str:
    """上下标：能整串映射就映射，否则保留定界符。

    回退分三种，区别只在**多字符要不要加括号**：

    - 单字符非字母数字（``^\\infty``）→ 直接顶上去 ``^∞``。加括号反而像函数调用。
    - 单字符字母数字（``W_q`` / ``a^n``）→ ``W\\_q`` / ``^n``，一个字符加括号是噪声。
    - 多字符（``^{-x^2}`` / ``^{d \\times d}``）→ **必须加括号**。Unicode 里没有
      ``⁻ˣ²`` 这种连续形式，直接拼出来的 ``e^-x²`` 会让指数范围读错，
      ``\\mathbb{R}^{d \\times d}`` 更会退化成 ``ℝ^d × d``（看着像叉乘）。
    """
    mapped = _script(plain, table)
    if mapped is not None:
        return mapped
    if len(plain) == 1:
        if not plain.isalnum():
            return plain
        return (r"\_" if marker == "_" else marker) + plain
    return f"{marker}({_escape_underscores(plain)})"


def _convert_math(expr: str) -> str:
    """一段数学表达式 → Unicode。不处理 ``$`` 定界符，那是 ``convert`` 的事。"""
    out: list[str] = []
    index = 0
    while index < len(expr):
        char = expr[index]

        if char == "\\":
            command = re.match(r"\\([A-Za-z]+)", expr[index:])
            if command:
                name = command.group(1)
                index += len(command.group(0))

                if name in DROP:
                    continue
                if name in SPACE:
                    out.append(" ")
                    continue
                if name in TIGHT:
                    continue
                if name == "frac" or name == "dfrac" or name == "tfrac":
                    numerator, index = _argument(expr, index)
                    denominator, index = _argument(expr, index)
                    top, bottom = _convert_math(numerator), _convert_math(denominator)
                    if _needs_parens(top):
                        top = f"({top})"
                    if _needs_parens(bottom):
                        bottom = f"({bottom})"
                    out.append(f"{top}/{bottom}")
                    continue
                if name == "sqrt":
                    degree = None
                    if index < len(expr) and expr[index] == "[":
                        degree, index = _bracket(expr, index)
                    body, index = _argument(expr, index)
                    body = _convert_math(body)
                    root = f"√({body})" if _needs_parens(body) else f"√{body}"
                    out.append(f"{_convert_math(degree)}{root}" if degree else root)
                    continue
                if name == "mathbb":
                    body, index = _argument(expr, index)
                    out.append("".join(BLACKBOARD.get(ch, ch) for ch in body))
                    continue
                if name in ACCENT:
                    body, index = _argument(expr, index)
                    drawn = _convert_math(body)
                    out.append(drawn + ACCENT[name] if len(drawn) == 1 else drawn)
                    continue
                if name in LITERAL:
                    body, index = _argument(expr, index)
                    out.append(body)
                    continue
                if name in WRAP:
                    body, index = _argument(expr, index)
                    out.append(_convert_math(body))
                    continue
                if name in SYMBOLS:
                    out.append(SYMBOLS[name])
                    continue
                # 不认识：去掉反斜杠保留名字，绝不吞字。
                out.append(name)
                continue

            pair = expr[index : index + 2]
            if pair == "\\\\":
                out.append("\n")
                index += 2
                continue
            if pair in ESCAPED:
                out.append(pair[1])
                index += 2
                continue
            if pair in SPACE:
                out.append(" ")
                index += 2
                continue
            if pair in TIGHT:
                index += 2
                continue
            index += 1
            continue

        if char in "^_":
            table = SUP if char == "^" else SUB
            argument, next_index = _argument(expr, index + 1)
            out.append(_script_or_fallback(char, _convert_math(argument), table))
            index = next_index
            continue

        if char == "{":
            body, index = _group(expr, index)
            out.append(_convert_math(body))
            continue

        if char == "}":
            index += 1
            continue

        out.append(char)
        index += 1

    # 括号**内侧**的空白没有语义，却会让 ``\left( \frac{a}{b} \right)`` 读成
    # ``( a/b )``。只抹贴边的那一层，括号中间的空白照留（``(a + b)``）。
    joined = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\s+\)", ")", re.sub(r"\(\s+", "(", joined))


def _split(source: str) -> Iterator[tuple[str, str]]:
    """切出 ``("code" | "math" | "text", 片段)``。``code`` 原样保留。"""
    segments: list[tuple[str, str]] = []
    buffer: list[str] = []
    index = 0
    length = len(source)
    at_line_start = True

    def flush() -> None:
        if buffer:
            segments.append(("text", "".join(buffer)))
            buffer.clear()

    while index < length:
        char = source[index]

        if at_line_start:
            fence = _FENCE.match(source, index)
            if fence:
                flush()
                closer = _closing_fence(source, fence.end(), fence.group(2))
                if closer < 0:
                    # 围栏还没闭合（流式中途）：剩下的一律当代码。
                    segments.append(("code", source[index:]))
                    return segments
                segments.append(("code", source[index:closer]))
                index = closer
                at_line_start = False
                continue

        if char == "`":
            ticks = _TICKS.match(source, index)
            assert ticks is not None
            marker = ticks.group(0)
            close = source.find(marker, index + len(marker))
            if close < 0:
                buffer.append(source[index:])
                break
            close += len(marker)
            flush()
            segments.append(("code", source[index:close]))
            index = close
            at_line_start = False
            continue

        if char == "$":
            display = source.startswith("$$", index)
            delimiter = "$$" if display else "$"
            kind, body, next_index = _math_body(source, index, delimiter, display)
            if kind == "open":
                # 半截公式不能报错，也不能吞掉后面的字：剩下的一律原样留下。
                buffer.append(source[index:])
                break
            if kind == "text":
                # 不是公式，但它不该连累后面的公式，所以只跳过定界符、继续扫。
                buffer.append(source[index:next_index])
                index = next_index
                at_line_start = False
                continue
            flush()
            segments.append(("math", body))
            index = next_index
            at_line_start = False
            continue

        if char == "\n":
            buffer.append(char)
            index += 1
            at_line_start = True
            continue

        nxt = _INTERESTING.search(source, index)
        stop = nxt.start() if nxt else length
        buffer.append(source[index:stop])
        index = stop
        at_line_start = False

    flush()
    return segments


def _closing_fence(source: str, position: int, fence: str) -> int:
    """找收尾围栏；返回它的行尾下标，找不到返回 -1。

    收尾围栏必须自己独占一行、同一种字符、不短于开头那条（CommonMark 的规矩，
    否则代码块里出现的 ``` 会把块提前截断）。
    """
    pattern = re.compile(
        rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", re.MULTILINE
    )
    match = pattern.search(source, position)
    return match.end() if match else -1


def _is_inline_math(body: str) -> bool:
    """行内 ``$…$`` 的内容像不像数学。

    认的是「有数学符号」或「单个字母」，**不是「短」**：``价格是 $5 到 $10`` 里
    两个 ``$`` 之间的内容是 ``5 到 ``，既不匹配符号也不匹配单字母，所以不转。
    """
    stripped = body.strip()
    if not stripped:
        return False
    if _INLINE_MATH_HINT.search(stripped):
        return True
    # ``isascii()`` 挡掉 ``$中$`` 这类：中文字母也 isalpha()。
    return bool(stripped.isascii() and _INLINE_MATH_LETTER.match(stripped))


def _math_body(
    source: str, index: int, delimiter: str, display: bool
) -> tuple[str, str, int]:
    """取 ``$…$`` / ``$$…$$``，返回 ``(处置, 内容, 新下标)``。

    - ``"math"``：``内容`` 是公式体，新下标在收尾定界符之后。
    - ``"text"``：这里不是公式。调用方把 ``source[index:新下标]`` 原样留下，
      **从新下标继续往下扫**。
    - ``"open"``：定界符没闭合（流式中途）。调用方把剩下的全部源码原样留下。

    ``"text"`` 和 ``"open"`` 必须分开：正文里一个孤立的 ``$``（「花了 $100」、
    「价格 $5 到 $10」）只该让**它自己**不转换。早先这里两种情况都当成「到此为止」，
    于是 `$k$` 后面的一整段 ``$\\text{rank}_i(d)$`` / ``$e^{-x^2}$`` 全部原样
    显示——截图里就是这么坏的。
    """
    start = index + len(delimiter)
    if display:
        close = source.find(delimiter, start)
        if close < 0:
            return "open", "", index
        return "math", source[start:close], close + len(delimiter)

    # 行内公式不跨行：跨行的 $ 几乎肯定是别的东西。
    newline = source.find("\n", start)
    stop = newline if newline >= 0 else len(source)
    close = source.find("$", start, stop)
    if close < 0:
        # 行内公式没有「半截」这回事——它不跨行，扫到行尾还没闭合就只能是个
        # 普通字符。所以这里也走 ``"text"``，后面的公式照样能转换。
        return "text", "", index + len(delimiter)
    body = source[start:close]
    if not _is_inline_math(body):
        # 认不出是公式（「价格是 $5 到 $10」）：不碰。
        return "text", "", index + len(delimiter)
    return "math", body, close + 1


def convert(source: str) -> str:
    """Markdown 源码里的 LaTeX → Unicode。代码块与行内代码原样保留。

    纯函数，流式输入下也安全：任何没闭合的定界符都原样留下。
    """
    if "$" not in source and "\\" not in source:
        return source

    out: list[str] = []
    for kind, piece in _split(source):
        if kind == "math":
            out.append(_convert_math(piece))
        else:
            out.append(piece)
    return "".join(out)
