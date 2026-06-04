#!/usr/bin/env python3
"""Tests for inline LaTeX pre-processing in the markdown renderer."""

from src.gui.utils import (
    _LATEX_SENTINEL_END,
    _LATEX_SENTINEL_START,
    _preprocess_inline_latex,
)

# --- Sentinel wrapping ---


def test_basic_alpha():
    result = _preprocess_inline_latex("Hello $\\alpha$ world")
    assert f"{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}" in result
    assert "$" not in result


def test_rightarrow_sentinel():
    result = _preprocess_inline_latex("$\\rightarrow$")
    assert f"{_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END}" in result


def test_currency_preserved():
    result = _preprocess_inline_latex("Price is $100 today")
    assert "$100" in result


def test_multiple_inline_latex():
    result = _preprocess_inline_latex("$\\alpha$ and $\\beta$")
    assert f"{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}" in result
    assert f"{_LATEX_SENTINEL_START}β{_LATEX_SENTINEL_END}" in result


# --- Inside bold ---


def test_bold_rightarrow():
    result = _preprocess_inline_latex("**Ten $\\rightarrow$ Nine $\\rightarrow$ Eight.**")
    assert f"**Ten {_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END} Nine" in result
    assert f"Nine {_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END} Eight.**" in result


def test_bold_greek():
    result = _preprocess_inline_latex("**$\\alpha$ to $\\omega$**")
    assert f"**{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}" in result
    assert f"{_LATEX_SENTINEL_START}ω{_LATEX_SENTINEL_END}**" in result


# --- Inside italic ---


def test_italic_beta():
    result = _preprocess_inline_latex("*$\\beta$ value*")
    assert f"*{_LATEX_SENTINEL_START}β{_LATEX_SENTINEL_END} value*" in result


# --- Inside bold+italic ---


def test_bold_italic_gamma():
    result = _preprocess_inline_latex("***$\\gamma$ ray***")
    assert f"***{_LATEX_SENTINEL_START}γ{_LATEX_SENTINEL_END} ray***" in result


# --- Inside strikethrough ---


def test_strikethrough_delta():
    result = _preprocess_inline_latex("~~$\\delta$ old~~")
    assert f"~~{_LATEX_SENTINEL_START}δ{_LATEX_SENTINEL_END} old~~" in result


# --- Header text ---


def test_header_alpha():
    result = _preprocess_inline_latex("The $\\alpha$ constant")
    assert f"The {_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END} constant" in result


# --- Blockquote text ---


def test_blockquote_theta():
    result = _preprocess_inline_latex("Where $\\theta$ is the angle")
    assert f"Where {_LATEX_SENTINEL_START}θ{_LATEX_SENTINEL_END} is the angle" in result


# --- Edge cases ---


def test_display_math_untouched():
    result = _preprocess_inline_latex("$$\\alpha$$")
    assert result == "$$\\alpha$$"


def test_empty_string():
    assert _preprocess_inline_latex("") == ""


def test_no_latex():
    assert _preprocess_inline_latex("Just plain text") == "Just plain text"


def test_complex_expression():
    result = _preprocess_inline_latex("If $x^2 + y^2 = r^2$ then circle")
    assert _LATEX_SENTINEL_START in result
    assert "$x" not in result


# --- User-reported case ---


def test_user_reported_bold_arrows():
    result = _preprocess_inline_latex("**Ten $\\rightarrow$ Nine $\\rightarrow$ Eight.**")
    assert "→" in result
    assert "**Ten" in result
    assert "Eight.**" in result
    assert "\\rightarrow" not in result
