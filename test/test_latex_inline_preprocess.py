#!/usr/bin/env python3
"""
Tests for inline LaTeX pre-processing in the markdown renderer.

Validates that $...$ LaTeX is correctly converted to Unicode even when
embedded inside markdown bold, italic, strikethrough, headers, and blockquotes.
"""

import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gui.utils import (
    _preprocess_inline_latex,
    _LATEX_SENTINEL_START,
    _LATEX_SENTINEL_END,
)
from src.gui.latex_renderer import latex_to_unicode

passed = 0
failed = 0


def check(name, result, expected):
    global passed, failed
    if expected in result:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        print(f"    Expected substring: {expected!r}")
        print(f"    Got:                {result!r}")
        failed += 1


def check_eq(name, result, expected):
    global passed, failed
    if result == expected:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        print(f"    Expected: {expected!r}")
        print(f"    Got:      {result!r}")
        failed += 1


def check_not(name, result, forbidden):
    """Pass if *forbidden* is NOT in result."""
    global passed, failed
    if forbidden not in result:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        print(f"    Forbidden substring found: {forbidden!r}")
        print(f"    Got:                        {result!r}")
        failed += 1


# =====================================================================
print("=" * 60)
print("Inline LaTeX Pre-processing Tests")
print("=" * 60)

# ----- Basic sentinel wrapping -----
print("\n[Sentinel wrapping]")

result = _preprocess_inline_latex("Hello $\\alpha$ world")
check("basic alpha", result, f"{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}")
check_not("no raw $", result, "$")

result = _preprocess_inline_latex("$\\rightarrow$")
check("rightarrow sentinel", result, f"{_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END}")

# Currency should be left alone
result = _preprocess_inline_latex("Price is $100 today")
check("currency preserved", result, "$100")

# Multiple inline LaTeX
result = _preprocess_inline_latex("$\\alpha$ and $\\beta$")
check("multiple - alpha", result, f"{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}")
check("multiple - beta", result, f"{_LATEX_SENTINEL_START}β{_LATEX_SENTINEL_END}")

# ----- Inside bold -----
print("\n[LaTeX inside bold]")

result = _preprocess_inline_latex("**Ten $\\rightarrow$ Nine $\\rightarrow$ Eight.**")
check("bold + rightarrow 1", result, f"**Ten {_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END} Nine")
check("bold + rightarrow 2", result, f"Nine {_LATEX_SENTINEL_START}→{_LATEX_SENTINEL_END} Eight.**")

result = _preprocess_inline_latex("**$\\alpha$ to $\\omega$**")
check("bold + greek start", result, f"**{_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END}")
check("bold + greek end", result, f"{_LATEX_SENTINEL_START}ω{_LATEX_SENTINEL_END}**")

# ----- Inside italic -----
print("\n[LaTeX inside italic]")

result = _preprocess_inline_latex("*$\\beta$ value*")
check("italic + beta", result, f"*{_LATEX_SENTINEL_START}β{_LATEX_SENTINEL_END} value*")

# ----- Inside bold+italic -----
print("\n[LaTeX inside bold+italic]")

result = _preprocess_inline_latex("***$\\gamma$ ray***")
check("bold_italic + gamma", result, f"***{_LATEX_SENTINEL_START}γ{_LATEX_SENTINEL_END} ray***")

# ----- Inside strikethrough -----
print("\n[LaTeX inside strikethrough]")

result = _preprocess_inline_latex("~~$\\delta$ old~~")
check("strikethrough + delta", result, f"~~{_LATEX_SENTINEL_START}δ{_LATEX_SENTINEL_END} old~~")

# ----- Header text -----
print("\n[LaTeX in header text]")

# Note: Headers are handled at the line level in render_markdown(),
# so _preprocess_inline_latex is called on the header content.
header_content = "The $\\alpha$ constant"
result = _preprocess_inline_latex(header_content)
check("header + alpha", result, f"The {_LATEX_SENTINEL_START}α{_LATEX_SENTINEL_END} constant")

# ----- Blockquote text -----
print("\n[LaTeX in blockquote text]")

blockquote_content = "Where $\\theta$ is the angle"
result = _preprocess_inline_latex(blockquote_content)
check("blockquote + theta", result, f"Where {_LATEX_SENTINEL_START}θ{_LATEX_SENTINEL_END} is the angle")

# ----- Edge cases -----
print("\n[Edge cases]")

# Display math $$ should NOT be touched
result = _preprocess_inline_latex("$$\\alpha$$")
check("display math untouched", result, "$$\\alpha$$")

# Empty string
result = _preprocess_inline_latex("")
check_eq("empty string", result, "")

# No LaTeX at all
result = _preprocess_inline_latex("Just plain text")
check_eq("no latex", result, "Just plain text")

# Complex expression
result = _preprocess_inline_latex("If $x^2 + y^2 = r^2$ then circle")
check("complex expr", result, _LATEX_SENTINEL_START)
check_not("complex no raw $", result, "$x")

# ----- The exact user-reported case -----
print("\n[User-reported case]")

user_text = "**Ten $\\rightarrow$ Nine $\\rightarrow$ Eight.**"
preprocessed = _preprocess_inline_latex(user_text)
# After preprocessing, the bold markers are still there but LaTeX is converted
check("user case - arrows converted", preprocessed, "→")
check("user case - bold preserved", preprocessed, "**Ten")
check("user case - bold end preserved", preprocessed, "Eight.**")
check_not("user case - no raw rightarrow", preprocessed, "\\rightarrow")

# =====================================================================
print("\n" + "=" * 60)
print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 60)

sys.exit(1 if failed else 0)
