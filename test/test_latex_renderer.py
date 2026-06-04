#!/usr/bin/env python3
"""Tests for the LaTeX-to-Unicode renderer."""

from src.gui.latex_renderer import extract_latex_blocks, latex_to_unicode

# --- Greek letters ---


def test_alpha():
    assert latex_to_unicode(r"\alpha") == "α"


def test_beta():
    assert latex_to_unicode(r"\beta") == "β"


def test_omega():
    assert latex_to_unicode(r"\Omega") == "Ω"


def test_gamma_delta():
    assert latex_to_unicode(r"\gamma + \delta") == "γ + δ"


# --- Operators ---


def test_times():
    assert latex_to_unicode(r"a \times b") == "a × b"


def test_neq():
    assert latex_to_unicode(r"a \neq b") == "a ≠ b"


def test_leq():
    assert latex_to_unicode(r"x \leq y") == "x ≤ y"


def test_approx():
    assert latex_to_unicode(r"\approx") == "≈"


def test_pm():
    assert latex_to_unicode(r"\pm") == "±"


def test_cdot():
    assert latex_to_unicode(r"a \cdot b") == "a · b"


# --- Arrows ---


def test_rightarrow():
    assert latex_to_unicode(r"\rightarrow") == "→"


def test_double_rightarrow():
    assert latex_to_unicode(r"\Rightarrow") == "⇒"


def test_implies():
    assert latex_to_unicode(r"\implies") == "⟹"


# --- Set theory ---


def test_in_operator():
    assert latex_to_unicode(r"x \in A") == "x ∈ A"


def test_forall():
    assert latex_to_unicode(r"\forall x") == "∀ x"


def test_exists():
    assert latex_to_unicode(r"\exists y") == "∃ y"


def test_subset():
    assert latex_to_unicode(r"A \subset B") == "A ⊂ B"


def test_emptyset():
    assert latex_to_unicode(r"\emptyset") == "∅"


# --- Superscripts ---


def test_x_squared():
    assert latex_to_unicode(r"x^2") == "x²"


def test_x_power_10():
    assert latex_to_unicode(r"x^{10}") == "x¹⁰"


def test_x_power_n_plus_1():
    assert latex_to_unicode(r"x^{n+1}") == "xⁿ⁺¹"


def test_euler_fallback():
    assert latex_to_unicode(r"e^{i\pi}") == "e^(iπ)"


# --- Subscripts ---


def test_a_subscript_0():
    assert latex_to_unicode(r"a_0") == "a₀"


def test_x_subscript_ij():
    assert latex_to_unicode(r"x_{ij}") == "xᵢⱼ"


def test_a_subscript_n():
    assert latex_to_unicode(r"a_n") == "aₙ"


# --- Fractions ---


def test_frac_simple():
    assert latex_to_unicode(r"\frac{a}{b}") == "a⁄b"


def test_frac_half():
    assert latex_to_unicode(r"\frac{1}{2}") == "1⁄2"


def test_frac_complex():
    assert latex_to_unicode(r"\frac{x+1}{y-1}") == "(x+1)⁄(y-1)"


# --- Square roots ---


def test_sqrt_simple():
    assert latex_to_unicode(r"\sqrt{x}") == "√x"


def test_sqrt_expr():
    assert latex_to_unicode(r"\sqrt{a+b}") == "√(a+b)"


def test_cbrt():
    assert latex_to_unicode(r"\sqrt[3]{x}") == "∛x"


def test_fourth_root():
    assert latex_to_unicode(r"\sqrt[4]{x}") == "∜x"


# --- Big operators ---


def test_sum():
    assert latex_to_unicode(r"\sum") == "∑"


def test_integral():
    assert latex_to_unicode(r"\int") == "∫"


def test_product():
    assert latex_to_unicode(r"\prod") == "∏"


def test_infinity():
    assert latex_to_unicode(r"\infty") == "∞"


# --- Math functions ---


def test_sin():
    assert latex_to_unicode(r"\sin(x)") == "sin(x)"


def test_log():
    assert latex_to_unicode(r"\log(x)") == "log(x)"


def test_lim():
    assert latex_to_unicode(r"\lim") == "lim"


# --- Spacing commands ---


def test_thin_space():
    assert latex_to_unicode(r"a \, b") == "a\u2009b"


def test_medium_space():
    assert latex_to_unicode(r"a \; b") == "a\u2005b"


def test_quad():
    assert latex_to_unicode(r"a \quad b") == "a\u2003b"


def test_negative_space():
    assert latex_to_unicode(r"a \! b") == "ab"


# --- Full expressions ---


def test_emc2():
    assert latex_to_unicode(r"E = mc^2") == "E = mc²"


def test_quadratic():
    assert latex_to_unicode(r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}") == "x = (-b ± √(b² - 4ac))⁄(2a)"


def test_euler():
    assert latex_to_unicode(r"e^{i\pi} + 1 = 0") == "e^(iπ) + 1 = 0"


def test_integral_with_dx():
    assert latex_to_unicode(r"\int_0^1 f(x) dx") == "∫₀¹ f(x) dx"


def test_sum_series():
    assert latex_to_unicode(r"\sum_{i=1}^{n} i^2") == "∑ᵢ₌₁ⁿ i²"


def test_integral_with_thin_space():
    assert latex_to_unicode(r"\int_a^b f(x) \, dx") == "∫ₐᵇ f(x)\u2009dx"


def test_sum_to_infinity():
    assert latex_to_unicode(r"\sum_{n=1}^{\infty} \frac{1}{n^2}") == "∑ₙ₌₁^(∞) 1⁄n²"


# --- Text commands ---


def test_text_command():
    assert latex_to_unicode(r"\text{hello}") == "hello"


def test_mathrm():
    assert latex_to_unicode(r"\mathrm{d}x") == "dx"


# --- Decorations ---


def test_hat():
    assert latex_to_unicode(r"\hat{x}") == "x\u0302"


def test_bar():
    assert latex_to_unicode(r"\bar{x}") == "x\u0304"


def test_vec():
    assert latex_to_unicode(r"\vec{v}") == "v\u20d7"


# --- Matrices ---


def test_pmatrix_structure():
    mat = latex_to_unicode(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
    assert "\n" in mat
    assert "╭" in mat
    assert "╰" in mat
    assert "a" in mat
    assert "d" in mat


def test_bmatrix_structure():
    bmat = latex_to_unicode(r"\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}")
    assert "┌" in bmat
    assert "└" in bmat


# --- Alignment ---


def test_matrix_alignment():
    aligned = latex_to_unicode(r"A = \begin{pmatrix} a \\ b \end{pmatrix}")
    lines = aligned.split("\n")
    assert len(lines) >= 2
    assert lines[0].strip().startswith("A =")
    padding = len(lines[1]) - len(lines[1].lstrip())
    assert padding >= 4


# --- Line breaks ---


def test_double_backslash():
    assert "\n" in latex_to_unicode(r"a \\ b")


# --- Edge cases ---


def test_empty_string():
    assert latex_to_unicode("") == ""


def test_plain_text():
    assert latex_to_unicode("hello world") == "hello world"


def test_number_only():
    assert latex_to_unicode("42") == "42"


def test_ldots():
    assert latex_to_unicode(r"\ldots") == "…"


def test_left_right():
    assert latex_to_unicode(r"\left( x \right)") == "( x )"


# --- Block extraction ---


def test_extract_inline_and_display():
    blocks = extract_latex_blocks(r"Text with $x^2$ inline and $$E = mc^2$$ display")
    assert len(blocks) == 2
    assert blocks[0][0] == "x^2"
    assert blocks[0][3] is False  # not display
    assert blocks[1][0] == "E = mc^2"
    assert blocks[1][3] is True  # display


def test_currency_not_matched():
    blocks = extract_latex_blocks("Price is $100 and $200")
    assert len(blocks) == 0


def test_mixed_latex_and_currency():
    blocks = extract_latex_blocks(r"We have $\alpha + \beta$ and also $50 total")
    assert len(blocks) == 1
