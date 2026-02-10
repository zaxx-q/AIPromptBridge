#!/usr/bin/env python3
"""
Lightweight LaTeX-to-Unicode renderer for chat window display.

Converts common LaTeX math expressions to Unicode text without
heavy dependencies (no matplotlib, sympy, etc.). Handles:
- Greek letters (\\alpha → α, \\Beta → Β)
- Operators (\\times → ×, \\neq → ≠)
- Arrows (\\rightarrow → →)
- Set theory (\\in → ∈, \\subset → ⊂)
- Superscripts and subscripts (x^2 → x², a_i → aᵢ)
- Fractions (\\frac{a}{b} → a⁄b)
- Square roots (\\sqrt{x} → √x)
- Summation, product, integral with limits
- Simple matrices (\\begin{pmatrix}...\\end{pmatrix})
- LaTeX spacing (\\, \\; \\quad etc.)
"""

import re
from typing import List, Tuple, Optional


# =============================================================================
# Unicode symbol mappings
# =============================================================================

# Greek lowercase
GREEK_LOWER = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\varepsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η',
    r'\theta': 'θ', r'\vartheta': 'ϑ', r'\iota': 'ι', r'\kappa': 'κ',
    r'\lambda': 'λ', r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ',
    r'\pi': 'π', r'\varpi': 'ϖ', r'\rho': 'ρ', r'\varrho': 'ϱ',
    r'\sigma': 'σ', r'\varsigma': 'ς', r'\tau': 'τ', r'\upsilon': 'υ',
    r'\phi': 'φ', r'\varphi': 'φ', r'\chi': 'χ', r'\psi': 'ψ',
    r'\omega': 'ω',
}

# Greek uppercase
GREEK_UPPER = {
    r'\Gamma': 'Γ', r'\Delta': 'Δ', r'\Theta': 'Θ', r'\Lambda': 'Λ',
    r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Sigma': 'Σ', r'\Upsilon': 'Υ',
    r'\Phi': 'Φ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
}

# Math operators and relations
OPERATORS = {
    r'\times': '×', r'\div': '÷', r'\cdot': '·', r'\ast': '∗',
    r'\star': '⋆', r'\circ': '∘', r'\bullet': '•',
    r'\pm': '±', r'\mp': '∓',
    r'\leq': '≤', r'\geq': '≥', r'\neq': '≠', r'\ne': '≠',
    r'\le': '≤', r'\ge': '≥',
    r'\approx': '≈', r'\cong': '≅', r'\equiv': '≡', r'\sim': '∼',
    r'\simeq': '≃', r'\propto': '∝',
    r'\ll': '≪', r'\gg': '≫',
    r'\prec': '≺', r'\succ': '≻',
    r'\preceq': '⪯', r'\succeq': '⪰',
}

# Set theory and logic
SET_LOGIC = {
    r'\in': '∈', r'\notin': '∉', r'\ni': '∋',
    r'\subset': '⊂', r'\supset': '⊃',
    r'\subseteq': '⊆', r'\supseteq': '⊇',
    r'\cup': '∪', r'\cap': '∩',
    r'\emptyset': '∅', r'\varnothing': '∅',
    r'\land': '∧', r'\lor': '∨', r'\neg': '¬', r'\lnot': '¬',
    r'\forall': '∀', r'\exists': '∃', r'\nexists': '∄',
    r'\setminus': '∖',
    r'\vee': '∨', r'\wedge': '∧',
}

# Arrows
ARROWS = {
    r'\leftarrow': '←', r'\rightarrow': '→',
    r'\leftrightarrow': '↔',
    r'\Leftarrow': '⇐', r'\Rightarrow': '⇒',
    r'\Leftrightarrow': '⇔',
    r'\uparrow': '↑', r'\downarrow': '↓',
    r'\mapsto': '↦', r'\to': '→',
    r'\gets': '←', r'\implies': '⟹', r'\iff': '⟺',
    r'\nearrow': '↗', r'\searrow': '↘',
    r'\nwarrow': '↖', r'\swarrow': '↙',
    r'\longrightarrow': '⟶', r'\longleftarrow': '⟵',
    r'\Longrightarrow': '⟹', r'\Longleftarrow': '⟸',
}

# Big operators / calculus
BIG_OPERATORS = {
    r'\sum': '∑', r'\prod': '∏', r'\coprod': '∐',
    r'\int': '∫', r'\iint': '∬', r'\iiint': '∭', r'\oint': '∮',
    r'\bigcup': '⋃', r'\bigcap': '⋂',
    r'\bigoplus': '⊕', r'\bigotimes': '⊗',
    r'\bigsqcup': '⊔',
}

# Miscellaneous symbols
MISC_SYMBOLS = {
    r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇',
    r'\hbar': 'ℏ', r'\ell': 'ℓ', r'\Re': 'ℜ', r'\Im': 'ℑ',
    r'\wp': '℘', r'\aleph': 'ℵ',
    r'\angle': '∠', r'\measuredangle': '∡',
    r'\triangle': '△', r'\square': '□',
    r'\diamond': '◇', r'\clubsuit': '♣', r'\diamondsuit': '♢',
    r'\heartsuit': '♡', r'\spadesuit': '♠',
    r'\flat': '♭', r'\natural': '♮', r'\sharp': '♯',
    r'\degree': '°', r'\celsius': '℃',
    r'\prime': '′', r'\dprime': '″',
    r'\dagger': '†', r'\ddagger': '‡',
    r'\checkmark': '✓', r'\maltese': '✠',
    r'\oplus': '⊕', r'\ominus': '⊖', r'\otimes': '⊗', r'\oslash': '⊘',
    r'\perp': '⊥', r'\parallel': '∥',
    r'\vdots': '⋮', r'\cdots': '⋯', r'\ldots': '…', r'\dots': '…',
    r'\ddots': '⋱',
    r'\langle': '⟨', r'\rangle': '⟩',
    r'\lceil': '⌈', r'\rceil': '⌉',
    r'\lfloor': '⌊', r'\rfloor': '⌋',
    r'\top': '⊤', r'\bot': '⊥',
    r'\models': '⊨', r'\vdash': '⊢', r'\dashv': '⊣',
}

# Math functions (rendered as upright text)
MATH_FUNCTIONS = {
    r'\sin': 'sin', r'\cos': 'cos', r'\tan': 'tan',
    r'\sec': 'sec', r'\csc': 'csc', r'\cot': 'cot',
    r'\arcsin': 'arcsin', r'\arccos': 'arccos', r'\arctan': 'arctan',
    r'\sinh': 'sinh', r'\cosh': 'cosh', r'\tanh': 'tanh',
    r'\ln': 'ln', r'\log': 'log', r'\exp': 'exp',
    r'\lim': 'lim', r'\limsup': 'lim sup', r'\liminf': 'lim inf',
    r'\max': 'max', r'\min': 'min', r'\sup': 'sup', r'\inf': 'inf',
    r'\arg': 'arg', r'\det': 'det', r'\dim': 'dim',
    r'\gcd': 'gcd', r'\hom': 'Hom', r'\ker': 'ker',
    r'\deg': 'deg', r'\Pr': 'Pr',
    r'\mod': 'mod', r'\bmod': 'mod',
}

# Combined symbol map (order: longer commands first to avoid partial matches)
SYMBOL_MAP = {}
SYMBOL_MAP.update(GREEK_LOWER)
SYMBOL_MAP.update(GREEK_UPPER)
SYMBOL_MAP.update(OPERATORS)
SYMBOL_MAP.update(SET_LOGIC)
SYMBOL_MAP.update(ARROWS)
SYMBOL_MAP.update(BIG_OPERATORS)
SYMBOL_MAP.update(MISC_SYMBOLS)
SYMBOL_MAP.update(MATH_FUNCTIONS)

# Sort by key length (longest first) for greedy matching
_SORTED_SYMBOLS = sorted(SYMBOL_MAP.keys(), key=len, reverse=True)


# =============================================================================
# Superscript / subscript Unicode maps
# =============================================================================

SUPERSCRIPT_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ',
    'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ',
    'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ',
    'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
    'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
    'T': 'ᵀ',
}

SUBSCRIPT_MAP = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
    'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
    'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
    'v': 'ᵥ', 'x': 'ₓ',
}

# Sentinel used in fallback to prevent re-processing by superscript/subscript loops
_SUPER_FALLBACK = '\x00SUP\x00'  # Will be cleaned up at the end
_SUB_FALLBACK = '\x00SUB\x00'


# =============================================================================
# Conversion helpers
# =============================================================================

def _to_superscript(text: str) -> str:
    """Convert text to Unicode superscript where possible.
    
    Uses a sentinel-based fallback to avoid re-processing by the superscript
    loop. The sentinel is cleaned up in latex_to_unicode().
    """
    result = []
    for ch in text:
        if ch in SUPERSCRIPT_MAP:
            result.append(SUPERSCRIPT_MAP[ch])
        elif ch == ' ':
            result.append(' ')
        else:
            # Fallback: use sentinel markers instead of ^ to prevent re-processing
            return f'{_SUPER_FALLBACK}({text})'
    return ''.join(result)


def _to_subscript(text: str) -> str:
    """Convert text to Unicode subscript where possible."""
    result = []
    for ch in text:
        if ch in SUBSCRIPT_MAP:
            result.append(SUBSCRIPT_MAP[ch])
        elif ch == ' ':
            result.append(' ')
        else:
            # Fallback: use sentinel markers instead of _ to prevent re-processing
            return f'{_SUB_FALLBACK}({text})'
    return ''.join(result)


def _extract_brace_content(text: str, pos: int) -> Tuple[Optional[str], int]:
    """
    Extract content within braces starting at pos.
    
    Args:
        text: The full text
        pos: Position of the opening '{' 
        
    Returns:
        (content, end_pos) where end_pos is the position after the closing '}'
        Returns (None, pos) if no valid brace group found.
    """
    if pos >= len(text) or text[pos] != '{':
        return None, pos
    
    depth = 0
    start = pos + 1
    for i in range(pos, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
    
    # Unbalanced braces - return content to end
    return text[start:], len(text)


def _process_fraction(text: str) -> str:
    """Process \\frac{num}{den} patterns."""
    pattern = r'\\frac\s*'
    result = text
    
    while True:
        match = re.search(pattern, result)
        if not match:
            break
        
        # Extract numerator
        num_content, after_num = _extract_brace_content(result, match.end())
        if num_content is None:
            break
        
        # Extract denominator
        den_content, after_den = _extract_brace_content(result, after_num)
        if den_content is None:
            break
        
        # Process inner LaTeX in numerator and denominator
        num_processed = latex_to_unicode(num_content)
        den_processed = latex_to_unicode(den_content)
        
        # Simple single-char fraction uses Unicode fraction slash
        if len(num_processed) <= 2 and len(den_processed) <= 2:
            replacement = f'{num_processed}⁄{den_processed}'
        else:
            replacement = f'({num_processed})⁄({den_processed})'
        
        result = result[:match.start()] + replacement + result[after_den:]
    
    return result


def _process_sqrt(text: str) -> str:
    """Process \\sqrt{x} and \\sqrt[n]{x} patterns."""
    result = text
    
    # \sqrt[n]{x} → ∛x (for n=3), ∜x (for n=4), or ⁿ√x
    while True:
        match = re.search(r'\\sqrt\s*\[([^\]]*)\]\s*', result)
        if not match:
            break
        
        n = match.group(1).strip()
        content, after = _extract_brace_content(result, match.end())
        if content is None:
            # Maybe no braces, take next single char
            if match.end() < len(result):
                content = result[match.end()]
                after = match.end() + 1
            else:
                break
        
        inner = latex_to_unicode(content)
        
        if n == '3':
            replacement = f'∛{inner}'
        elif n == '4':
            replacement = f'∜{inner}'
        else:
            n_super = _to_superscript(n)
            replacement = f'{n_super}√{inner}'
        
        result = result[:match.start()] + replacement + result[after:]
    
    # \sqrt{x} → √x
    while True:
        match = re.search(r'\\sqrt\s*', result)
        if not match:
            break
        
        content, after = _extract_brace_content(result, match.end())
        if content is None:
            if match.end() < len(result):
                content = result[match.end()]
                after = match.end() + 1
            else:
                break
        
        inner = latex_to_unicode(content)
        replacement = f'√({inner})' if len(inner) > 1 else f'√{inner}'
        result = result[:match.start()] + replacement + result[after:]
    
    return result


def _process_superscript(text: str) -> str:
    """Process ^{content} and ^x patterns."""
    result = text
    
    # ^{content} — braced superscript
    while True:
        match = re.search(r'\^', result)
        if not match:
            break
        
        pos = match.end()
        if pos >= len(result):
            break
        
        if result[pos] == '{':
            content, after = _extract_brace_content(result, pos)
            if content is None:
                break
            # Recursively process inner content first
            inner = latex_to_unicode(content)
            sup = _to_superscript(inner)
            result = result[:match.start()] + sup + result[after:]
        else:
            # Single character superscript
            ch = result[pos]
            sup = _to_superscript(ch)
            result = result[:match.start()] + sup + result[pos + 1:]
    
    return result


def _process_subscript(text: str) -> str:
    """Process _{content} and _x patterns."""
    result = text
    
    while True:
        # Find _ that is NOT part of a LaTeX command (not preceded by \)
        match = re.search(r'(?<!\\)_', result)
        if not match:
            break
        
        pos = match.end()
        if pos >= len(result):
            break
        
        if result[pos] == '{':
            content, after = _extract_brace_content(result, pos)
            if content is None:
                break
            inner = latex_to_unicode(content)
            sub = _to_subscript(inner)
            result = result[:match.start()] + sub + result[after:]
        else:
            # Single character subscript
            ch = result[pos]
            sub = _to_subscript(ch)
            result = result[:match.start()] + sub + result[pos + 1:]
    
    return result


def _process_matrices(text: str, _depth: int = 0) -> str:
    """Process \\begin{pmatrix/bmatrix/vmatrix/matrix}...\\end{...} environments."""
    if _depth > 50:
        return text

    # Map environment names to bracket styles:
    # (left_top, left_mid, left_bot, right_top, right_mid, right_bot)
    bracket_styles = {
        'pmatrix': ('╭', '│', '╰', '╮', '│', '╯'),         # Box drawing arcs (parens)
        'bmatrix': ('┌', '│', '└', '┐', '│', '┘'),         # Box drawing brackets
        'Bmatrix': ('⎧', '⎨', '⎩', '⎫', '⎬', '⎭'),         # Curly braces (Unicode parts)
        'vmatrix': ('│', '│', '│', '│', '│', '│'),         # Vertical bars
        'Vmatrix': ('║', '║', '║', '║', '║', '║'),         # Double vertical bars
        'matrix':  (' ', ' ', ' ', ' ', ' ', ' '),         # No brackets
        'smallmatrix': (' ', ' ', ' ', ' ', ' ', ' '),     # No brackets
    }
    
    result = text
    
    # Iterate over all matrix types
    for env_name, style in bracket_styles.items():
        lt, lm, lb, rt, rm, rb = style
        pattern = re.compile(
            r'\\begin\s*\{' + re.escape(env_name) + r'\}\s*'
            r'(.*?)'
            r'\s*\\end\s*\{' + re.escape(env_name) + r'\}',
            re.DOTALL
        )
        
        while True:
            match = pattern.search(result)
            if not match:
                break
            
            # --- ALIGNMENT FIX ---
            # Calculate visual length of the text before the matrix starts
            # so we can indent subsequent lines of the matrix to align with the first line.
            prefix = result[:match.start()]
            # Recursively process prefix to get visual character count
            # We assume the prefix is valid LaTeX or text up to this point.
            try:
                # FIX: Naive stripping fails for symbols like \alpha (1 char) vs \alpha (6 chars).
                # We must render the prefix to know its true visual width.
                # Recursive call is safe because `prefix` is a strictly smaller substring.
                # and we increase depth to avoid infinite recursion loops if something goes wrong.
                vis_prefix_full = latex_to_unicode(prefix, _depth + 1, preserve_spaces=True)
                
                # We only care about the last line of the prefix for indentation
                if '\n' in vis_prefix_full:
                    vis_prefix = vis_prefix_full.split('\n')[-1]
                else:
                    vis_prefix = vis_prefix_full
                    
                padding = ' ' * len(vis_prefix)
            except Exception:
                # Fallback if something goes wrong
                padding = ''
            
            body = match.group(1).strip()
            
            # Parse rows separated by \\ and cells by &
            raw_rows = re.split(r'\\\\', body)
            matrix_rows = []
            for row in raw_rows:
                row = row.strip()
                if not row:
                    continue
                # Process cell content (recursive)
                cells = [latex_to_unicode(c.strip(), _depth + 1) for c in row.split('&')]
                matrix_rows.append(cells)
            
            if not matrix_rows:
                result = result[:match.start()] + result[match.end():]
                continue
            
            # Calculate column widths
            num_cols = max(len(r) for r in matrix_rows)
            col_widths = [0] * num_cols
            for row in matrix_rows:
                for j, cell in enumerate(row):
                    if j < num_cols:
                        col_widths[j] = max(col_widths[j], len(cell))
            
            # Render as aligned text with brackets
            rendered_rows = []
            for row in matrix_rows:
                # Pad row to have correct number of columns
                while len(row) < num_cols:
                    row.append('')
                # Align cells
                cells_str = '  '.join(cell.ljust(col_widths[j]) for j, cell in enumerate(row))
                rendered_rows.append(cells_str)
            
            # Build output with brackets on each line
            lines = []
            n_rows = len(rendered_rows)
            for i, row_str in enumerate(rendered_rows):
                row_str = row_str.rstrip()
                
                # Determine brackets for this line
                if n_rows == 1:
                    # Single row -> use brackets that look like [ ... ]
                    l, r = lt, rt 
                    if env_name == 'pmatrix': l, r = '(', ')'
                    elif env_name == 'bmatrix': l, r = '[', ']'
                elif i == 0:
                    l, r = lt, rt
                elif i == n_rows - 1:
                    l, r = lb, rb
                else:
                    l, r = lm, rm
                
                # Add padding to lines after the first
                line_padding = padding if i > 0 else ''
                lines.append(f'{line_padding}{l} {row_str} {r}')
            
            replacement = '\n'.join(lines)
            result = result[:match.start()] + replacement + result[match.end():]
    
    return result


# =============================================================================
# Main conversion function
# =============================================================================

def latex_to_unicode(latex_str: str, _depth: int = 0, preserve_spaces: bool = False) -> str:
    """
    Convert a LaTeX math expression to Unicode text.
    
    This strips the $ delimiters if present and converts LaTeX commands
    to their Unicode equivalents.
    
    Args:
        latex_str: LaTeX math string (with or without $ delimiters)
        preserve_spaces: If True, do not strip leading/trailing whitespace from the result.
        
    Returns:
        Unicode representation of the math expression
    """
    if not latex_str:
        return latex_str
    
    if preserve_spaces:
        text = latex_str
    else:
        text = latex_str.strip()
    
    # Strip $ delimiters if present
    # If preserve_spaces is True, we check the stripped version for delimiters
    # but still return the content stripped of delimiters (because delimiters shouldn't be rendered).
    # The prefix calculation usually doesn't involve $ delimiters.
    
    stripped_text = text.strip()
    if stripped_text.startswith('$$') and stripped_text.endswith('$$'):
        text = stripped_text[2:-2].strip()
    elif stripped_text.startswith('$') and stripped_text.endswith('$'):
        text = stripped_text[1:-1].strip()
    
    # Process \text{} — render content as-is
    text = re.sub(r'\\text\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textbf\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textit\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\mathrm\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\mathbf\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\mathit\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\mathcal\s*\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\mathbb\s*\{([^}]*)\}', r'\1', text)
    
    # Process \overline{x} → x̄  (combining macron U+0304)
    text = re.sub(r'\\overline\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0304', text)
    text = re.sub(r'\\bar\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0304', text)
    
    # Process \hat{x} → x̂  (combining circumflex U+0302)
    text = re.sub(r'\\hat\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0302', text)
    
    # Process \tilde{x} → x̃  (combining tilde U+0303)
    text = re.sub(r'\\tilde\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0303', text)
    
    # Process \vec{x} → x⃗  (combining arrow U+20D7)
    text = re.sub(r'\\vec\s*\{([^}]*)\}', lambda m: m.group(1) + '\u20D7', text)
    
    # Process \dot{x} → ẋ  (combining dot above U+0307)
    text = re.sub(r'\\dot\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0307', text)
    
    # Process \ddot{x} → ẍ  (combining diaeresis U+0308)
    text = re.sub(r'\\ddot\s*\{([^}]*)\}', lambda m: m.group(1) + '\u0308', text)
    
    # Process matrices before fractions (matrices may contain fractions)
    text = _process_matrices(text, _depth + 1)
    
    # Process fractions before other transformations
    text = _process_fraction(text)
    
    # Process square roots
    text = _process_sqrt(text)
    
    # Process LaTeX spacing commands BEFORE symbol replacement
    # \, → thin space, \; → medium space, \: → medium space
    # \! → nothing (negative thin space), \  → space
    # \quad → em space, \qquad → 2 em spaces
    
    # Handle \\ line breaks that aren't in matrices (standalone)
    # Must be done BEFORE backslash-space handling to avoid consuming the second backslash
    text = text.replace('\\\\', '\n')
    
    # Spacing commands (consume surrounding spaces)
    text = re.sub(r'\s*\\,\s*', '\u2009', text)      # Thin space
    text = re.sub(r'\s*\\;\s*', '\u2005', text)      # Medium mathematical space
    text = re.sub(r'\s*\\:\s*', '\u2005', text)      # Medium mathematical space
    text = re.sub(r'\s*\\!\s*', '', text)            # Negative thin space
    text = re.sub(r'\s*\\\s\s*', ' ', text)          # Backslash-space → regular space
    text = re.sub(r'\s*\\quad\s*', '\u2003', text)   # Em space
    text = re.sub(r'\s*\\qquad\s*', '\u2003\u2003', text)  # Double em space
    
    # Replace LaTeX commands with Unicode symbols (longest match first)
    for cmd in _SORTED_SYMBOLS:
        if cmd in text:
            # Use word boundary to avoid partial replacement of commands
            # e.g., don't replace \in when processing \int
            escaped = re.escape(cmd)
            # Match command followed by non-alpha (boundary) or end of string
            text = re.sub(escaped + r'(?![a-zA-Z])', SYMBOL_MAP[cmd], text)
    
    # Process superscripts and subscripts AFTER symbol replacement
    text = _process_superscript(text)
    text = _process_subscript(text)
    
    # Clean up: remove \left and \right (they're just sizing hints)
    text = re.sub(r'\\left\s*', '', text)
    text = re.sub(r'\\right\s*', '', text)
    
    # Handle \\ line breaks that aren't in matrices (standalone)
    # Already handled earlier
    # text = text.replace('\\\\', '\n')
    
    # Remove remaining \commands that weren't matched (graceful degradation)
    # But keep the argument: \unknown{content} → content
    text = re.sub(r'\\[a-zA-Z]+\s*\{([^}]*)\}', r'\1', text)
    # Remove bare unknown commands: \unknown → (empty)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    
    # Clean up remaining braces (grouping artifacts)
    text = text.replace('{', '').replace('}', '')
    
    # Clean up sentinel fallback markers → readable notation
    text = text.replace(_SUPER_FALLBACK, '^')
    text = text.replace(_SUB_FALLBACK, '_')
    
    # Clean up & (alignment markers in non-matrix contexts)
    text = text.replace('&', ' ')
    
    # Collapse multiple spaces (but preserve newlines and indentation)
    # Only collapse ASCII spaces to preserve special Unicode spaces (\u2009 etc.)
    # Use positive lookbehind (?<=\S) to only collapse spaces that follow a non-whitespace character
    text = re.sub(r'(?<=\S) {2,}', ' ', text)
    
    # Trim spaces around operators for cleaner look
    if not preserve_spaces:
        text = text.strip()
    
    return text


# =============================================================================
# Block extraction for markdown integration
# =============================================================================

def extract_latex_blocks(text: str) -> List[Tuple[str, int, int, bool]]:
    """
    Find $...$ and $$...$$ LaTeX spans in text.
    
    Returns a list of tuples: (latex_content, start, end, is_display)
    where is_display is True for $$...$$ blocks.
    
    Dollar signs that look like currency (e.g., "$100") are not matched.
    Requires non-space after opening $ and non-space before closing $.
    """
    blocks = []
    
    # First find $$...$$ display math (can span lines)
    for match in re.finditer(r'\$\$(.+?)\$\$', text, re.DOTALL):
        content = match.group(1).strip()
        if content:  # Skip empty
            blocks.append((content, match.start(), match.end(), True))
    
    # Then find $...$ inline math (single line only)
    # Avoid matching inside already-found $$ blocks
    display_ranges = [(b[1], b[2]) for b in blocks]
    
    for match in re.finditer(r'(?<!\$)\$(?!\$)(\S(?:[^$]*?\S)?)\$(?!\$)', text):
        start, end = match.start(), match.end()
        content = match.group(1)
        
        # Skip if inside a display block
        inside_display = False
        for ds, de in display_ranges:
            if start >= ds and end <= de:
                inside_display = True
                break
        
        if not inside_display and content.strip():
            # Skip if this looks like currency ($ followed by digits only)
            if re.match(r'^\d[\d,]*\.?\d*$', content):
                continue
            blocks.append((content, start, end, False))
    
    # Sort by position
    blocks.sort(key=lambda b: b[1])
    return blocks
