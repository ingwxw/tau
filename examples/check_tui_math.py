"""数学公式：LaTeX 在进 Rich 之前变成 Unicode，且代码与流式输入都不受影响。

三条不看这个检查就发现不了的：

1. **必须在源码层跑。** ``rank_i`` 的下划线一旦进了 Markdown 就是强调标记，两个
   ``_`` 配成对之后整段变斜体，那时再想还原已经拿不到原始字符了。检查里既钉了
   ``convert`` 的返回值，也在 ``render_markdown`` 的出口上钉了一遍「没有斜体」。
2. **代码块和行内代码是代码。** 里面的 ``$`` / ``\\frac`` 原样保留，否则一段
   shell 脚本或一个正则会被翻译得面目全非。
3. **半截公式不能报错、不能吞字。** 公式是跟着流一段段进来的，``$$…`` 只到了一半
   时剩下的一律原样留着；看错了宁可不转（``价格是 $5 到 $10`` 不是公式）。
4. **认错一个不能连累后面。** 这里踩过坑：``$k$`` 这类不带 ``\\`` / ``^`` / ``_``
   的内容早先被当成「不是公式」，而那次判定直接**终止了整篇的扫描**——于是它后面
   的 ``$\\text{rank}_i(d)$`` / ``$e^{-x^2}$`` 全长这样原样显示在屏幕上。
"""

from tau_coding.tui.latex import convert
from tau_coding.tui.markdown import render_markdown

#: 用户截图里那条 RRF 打分公式，逐字符钉住。
RRF = r"$$score(d) = \sum_i \frac{1}{k + \text{rank}_i(d)}$$"

RRF_PLAIN = "score(d) = ∑ᵢ 1/(k + rankᵢ(d))"


def check_rrf_formula() -> None:
    """``\\frac`` 的括号是逐边判断的：``1/(k + …)``，不是 ``(1)/(k + …)``。"""
    assert convert(RRF) == RRF_PLAIN, convert(RRF)


def check_symbols_and_scripts() -> None:
    assert convert(r"$\alpha \le \beta \neq \gamma \to \infty$") == "α ≤ β ≠ γ → ∞"

    # 上标是逐字符映射的，Unicode 里没有的走 ``^(...)`` 回退——不能拼成
    # ``e^-x²``，那个指数范围会读错。
    assert convert(r"$e^{-x^2}$") == "e^(-x²)"
    assert convert(r"$x_i^2$") == "xᵢ²"

    # ``\sqrt`` 带可选参数时开方次数写在根号左边。
    assert convert(r"$$\sqrt{x^2 + y^2}$$") == "√(x² + y²)"
    assert convert(r"$$\sqrt[3]{x}$$") == "3√x"

    # 黑板体；``\mathbb{R}^{d \times d}`` 的指数必须带括号，否则读成叉乘。
    assert convert(r"$$\mathbb{R}$$") == "ℝ"
    assert convert(r"$$\mathbb{R}^{d \times d}$$") == "ℝ^(d × d)"

    # 括号内侧的空白来自源码，没有语义，抹掉。
    assert convert(r"$$\left( \frac{a}{b} \right)$$") == "(a/b)"

    # 字表覆盖不到的上下标保留定界符，但 ``_`` 必须转义：两个裸下划线会被
    # Markdown 配成一对，整段变斜体。
    assert convert(r"$$W_q, X_q$$") == r"W\_q, X\_q"

    # 不认识的命令去掉反斜杠保留名字，绝不吞字。
    unknown = convert(r"$$\foobar{x}$$")
    assert "foobar" in unknown and "\\" not in unknown, unknown


def check_inline_detection() -> None:
    """行内 ``$…$``：认得出单个字母变量，不认金额，认错一个不连累后面。"""
    # 单个字母是模型最常写的行内变量，漏掉它一整段就全是 ``$`` 加字母。
    assert convert("其中 $k$ 通常取 60，$d$ 是文档。") == "其中 k 通常取 60，d 是文档。"

    # 但门槛不能放宽成「短」：金额后面跟的是数字，两个 ``$`` 之间是正文。
    assert convert("价格是 $5 到 $10 之间") == "价格是 $5 到 $10 之间"
    assert convert("在美国卖 $5$10 两个价") == "在美国卖 $5$10 两个价"
    # 中文字也 isalpha()，只认 ASCII 才挡得住。
    assert convert("变量 $中$ 不是公式") == "变量 $中$ 不是公式"

    # 这一条是回归：早先一个不认识的 ``$`` 会把整篇的扫描从此掐断。
    line = r"其中 $k$ 取 60，$\text{rank}_i(d)$ 是名次。"
    assert convert(line) == r"其中 k 取 60，rankᵢ(d) 是名次。", convert(line)


def check_code_untouched() -> None:
    """围栏代码块与行内代码里的 ``$`` / ``\\frac`` 是代码，原样保留。"""
    fenced = "看这段：\n\n```sh\necho $HOME $$ \\frac{1}{2}\n```\n"
    assert convert(fenced) == fenced, convert(fenced)

    inline = r"行内 `$\frac{1}{2}$` 原样"
    assert convert(inline) == inline, convert(inline)

    # 围栏没闭合（流式中途）时，剩下的一律当代码，不能掉进公式解析。
    half = "```python\nx = 1  # $5\n"
    assert convert(half) == half, convert(half)


def check_streaming_edges() -> None:
    """没闭合的定界符原样留下，不报错也不吞掉后面的字。"""
    assert convert(r"正在推：$$\sum_i \frac{1}{k") == r"正在推：$$\sum_i \frac{1}{k"
    assert convert(r"行内 $x^2 还没闭合") == r"行内 $x^2 还没闭合"

    # 看错了宁可不转：正文里的美元金额不是公式。
    price = "价格是 $5 到 $10 之间"
    assert convert(price) == price, convert(price)

    # 没有 ``$`` 也没有 ``\\`` 的源码直接短路返回，连扫都不扫。
    plain = "一段普通正文，带 `代码` 和 # 号。"
    assert convert(plain) == plain


def check_render_pipeline() -> None:
    """接进 ``render_markdown``：公式在 Rich 之前就已经是 Unicode。"""
    content = render_markdown(f"RRF 的打分是：\n\n{RRF}\n", 60)
    text = content.plain

    assert "$$" not in text and "\\" not in text, f"公式没被转换：\n{text}"
    assert RRF_PLAIN in text, f"公式转换结果不对：\n{text}"

    # 这一段不该有任何样式。下划线要是没在源码层处理掉，Markdown 会把
    # ``\sum_i`` 和 ``rank_i`` 的两个 ``_`` 配成一对，整段变斜体。
    styled = [
        span.style
        for span in content.spans
        if text[span.start : span.end].strip()
    ]
    assert not any(style.italic for style in styled), (
        f"公式被当成强调标记了：{[s for s in styled if s.italic]}"
    )


def main() -> None:
    check_rrf_formula()
    check_symbols_and_scripts()
    check_inline_detection()
    check_code_untouched()
    check_streaming_edges()
    check_render_pipeline()
    print("TUI 数学公式检查通过")


if __name__ == "__main__":
    main()
