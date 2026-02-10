#!/usr/bin/env python3
"""
Tests for the LaTeX-to-Unicode renderer.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.gui.latex_renderer import latex_to_unicode, extract_latex_blocks

passed = 0
failed = 0

def check(label, result, expected):
    global passed, failed
    if result == expected:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")
        print(f"        Expected: {expected!r}")
        print(f"        Got:      {result!r}")


print("=" * 60)
print("LaTeX Renderer Tests")
print("=" * 60)

# --- Greek letters ---
print("\n[Greek Letters]")
check("alpha", latex_to_unicode(r"\alpha"), "α")
check("beta", latex_to_unicode(r"\beta"), "β")
check("Omega", latex_to_unicode(r"\Omega"), "Ω")
check("gamma delta", latex_to_unicode(r"\gamma + \delta"), "γ + δ")

# --- Operators ---
print("\n[Operators]")
check("times", latex_to_unicode(r"a \times b"), "a × b")
check("neq", latex_to_unicode(r"a \neq b"), "a ≠ b")
check("leq", latex_to_unicode(r"x \leq y"), "x ≤ y")
check("approx", latex_to_unicode(r"\approx"), "≈")
check("pm", latex_to_unicode(r"\pm"), "±")
check("cdot", latex_to_unicode(r"a \cdot b"), "a · b")

# --- Arrows ---
print("\n[Arrows]")
check("rightarrow", latex_to_unicode(r"\rightarrow"), "→")
check("Rightarrow", latex_to_unicode(r"\Rightarrow"), "⇒")
check("implies", latex_to_unicode(r"\implies"), "⟹")

# --- Set theory ---
print("\n[Set Theory & Logic]")
check("in", latex_to_unicode(r"x \in A"), "x ∈ A")
check("forall", latex_to_unicode(r"\forall x"), "∀ x")
check("exists", latex_to_unicode(r"\exists y"), "∃ y")
check("subset", latex_to_unicode(r"A \subset B"), "A ⊂ B")
check("emptyset", latex_to_unicode(r"\emptyset"), "∅")

# --- Superscripts ---
print("\n[Superscripts]")
check("x^2", latex_to_unicode(r"x^2"), "x²")
check("x^{10}", latex_to_unicode(r"x^{10}"), "x¹⁰")
check("x^{n+1}", latex_to_unicode(r"x^{n+1}"), "xⁿ⁺¹")
check("e^{ipi} fallback", latex_to_unicode(r"e^{i\pi}"), "e^(iπ)")  # π has no superscript → clean fallback

# --- Subscripts ---
print("\n[Subscripts]")
check("a_0", latex_to_unicode(r"a_0"), "a₀")
check("x_{ij}", latex_to_unicode(r"x_{ij}"), "xᵢⱼ")
check("a_n", latex_to_unicode(r"a_n"), "aₙ")

# --- Fractions ---
print("\n[Fractions]")
check("frac simple", latex_to_unicode(r"\frac{a}{b}"), "a⁄b")
check("frac 1/2", latex_to_unicode(r"\frac{1}{2}"), "1⁄2")
check("frac complex", latex_to_unicode(r"\frac{x+1}{y-1}"), "(x+1)⁄(y-1)")

# --- Square roots ---
print("\n[Square Roots]")
check("sqrt simple", latex_to_unicode(r"\sqrt{x}"), "√x")
check("sqrt expr", latex_to_unicode(r"\sqrt{a+b}"), "√(a+b)")
check("cbrt", latex_to_unicode(r"\sqrt[3]{x}"), "∛x")
check("4th root", latex_to_unicode(r"\sqrt[4]{x}"), "∜x")

# --- Big operators ---
print("\n[Big Operators]")
check("sum", latex_to_unicode(r"\sum"), "∑")
check("int", latex_to_unicode(r"\int"), "∫")
check("prod", latex_to_unicode(r"\prod"), "∏")
check("infty", latex_to_unicode(r"\infty"), "∞")

# --- Math functions ---
print("\n[Math Functions]")
check("sin", latex_to_unicode(r"\sin(x)"), "sin(x)")
check("log", latex_to_unicode(r"\log(x)"), "log(x)")
check("lim", latex_to_unicode(r"\lim"), "lim")

# --- Spacing commands ---
print("\n[Spacing Commands]")
check("thin space \\,", latex_to_unicode(r"a \, b"), "a\u2009b")
check("medium space \\;", latex_to_unicode(r"a \; b"), "a\u2005b")
check("quad", latex_to_unicode(r"a \quad b"), "a\u2003b")
check("negative \\!", latex_to_unicode(r"a \! b"), "ab")

# --- Combined expressions ---
print("\n[Full Expressions]")
check("E=mc^2", latex_to_unicode(r"E = mc^2"), "E = mc²")
check("quadratic", latex_to_unicode(r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}"),
      "x = (-b ± √(b² - 4ac))⁄(2a)")
check("euler fallback", latex_to_unicode(r"e^{i\pi} + 1 = 0"), "e^(iπ) + 1 = 0")
check("integral with dx", latex_to_unicode(r"\int_0^1 f(x) dx"), "∫₀¹ f(x) dx")
check("sum series", latex_to_unicode(r"\sum_{i=1}^{n} i^2"), "∑ᵢ₌₁ⁿ i²")
# The problematic formula from user report:
check("integral with \\,", latex_to_unicode(r"\int_a^b f(x) \, dx"), "∫ₐᵇ f(x)\u2009dx")
check("sum to infinity", latex_to_unicode(r"\sum_{n=1}^{\infty} \frac{1}{n^2}"), "∑ₙ₌₁^(∞) 1⁄n²")

# --- Text commands ---
print("\n[Text Commands]")
check("text", latex_to_unicode(r"\text{hello}"), "hello")
check("mathrm", latex_to_unicode(r"\mathrm{d}x"), "dx")

# --- Decorations ---
print("\n[Decorations]")
check("hat", latex_to_unicode(r"\hat{x}"), "x\u0302")
check("bar", latex_to_unicode(r"\bar{x}"), "x\u0304")
check("vec", latex_to_unicode(r"\vec{v}"), "v\u20D7")

# --- Matrices ---
print("\n[Matrices]")
mat_2x2 = latex_to_unicode(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
check("pmatrix has lines", '\n' in mat_2x2, True)
check("pmatrix has ╭", '╭' in mat_2x2, True)
check("pmatrix has ╰", '╰' in mat_2x2, True)
check("pmatrix has a", 'a' in mat_2x2, True)
check("pmatrix has d", 'd' in mat_2x2, True)

bmat = latex_to_unicode(r"\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}")
check("bmatrix has ┌", '┌' in bmat, True)
check("bmatrix has └", '└' in bmat, True)

# --- Alignment ---
print("\n[Matrix Alignment]")
aligned = latex_to_unicode(r"A = \begin{pmatrix} a \\ b \end{pmatrix}")
# latex_to_unicode strips 'A = ' in some cases? No.
lines = aligned.split('\n')
if len(lines) >= 2:
    check("aligned line 1 starts with A", lines[0].strip().startswith("A ="), True)
    # Check that line 2 starts with spaces (padding)
    # Since 'A = ' is 4 chars, we expect indentation
    padding_match = len(lines[1]) - len(lines[1].lstrip())
    check("aligned line 2 indent", padding_match >= 4, True)
else:
    check("not aligned (single line?)", False, True)

# --- \\ line breaks ---
print("\n[Line Breaks]")
check("double backslash", '\n' in latex_to_unicode(r"a \\ b"), True)

# --- Edge cases ---
print("\n[Edge Cases]")
check("empty string", latex_to_unicode(""), "")
check("plain text", latex_to_unicode("hello world"), "hello world")
check("number only", latex_to_unicode("42"), "42")
check("dot products", latex_to_unicode(r"\ldots"), "…")
check("left right", latex_to_unicode(r"\left( x \right)"), "( x )")

# --- Block extraction ---
print("\n[Block Extraction]")
blocks = extract_latex_blocks(r"Text with $x^2$ inline and $$E = mc^2$$ display")
check("found 2 blocks", len(blocks), 2)
if len(blocks) >= 2:
    check("inline content", blocks[0][0], "x^2")
    check("inline is_display", blocks[0][3], False)
    check("display content", blocks[1][0], "E = mc^2")
    check("display is_display", blocks[1][3], True)

# Currency skip
blocks2 = extract_latex_blocks("Price is $100 and $200")
check("currency not matched", len(blocks2), 0)

# Mixed
blocks3 = extract_latex_blocks(r"We have $\alpha + \beta$ and also $50 total")
check("mixed: 1 block (skips currency)", len(blocks3), 1)

# --- Summary ---
print("\n" + "=" * 60)
print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
