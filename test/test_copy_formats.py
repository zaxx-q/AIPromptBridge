#!/usr/bin/env python3
"""Tests for markdown to HTML conversion and plaintext formatting."""

from src.gui.utils import markdown_to_html
from src.utils import strip_markdown


def test_markdown_to_html_headers():
    text = "# Header 1\n## Header 2"
    expected = "<h1>Header 1</h1>\n<h2>Header 2</h2>"
    assert markdown_to_html(text) == expected


def test_markdown_to_html_bold_italic():
    text = "This is **bold** and *italic* and ***bold-italic***."
    expected = "<p>This is <strong>bold</strong> and <em>italic</em> and <strong><em>bold-italic</em></strong>.</p>"
    assert markdown_to_html(text) == expected


def test_markdown_to_html_lists():
    text = "- item 1\n- item 2"
    # Note: markdown_to_html closes any open list on the final step
    expected = "<ul>\n<li>item 1</li>\n<li>item 2</li>\n</ul>"
    assert markdown_to_html(text) == expected


def test_markdown_to_html_code_block():
    text = "Here is some code:\n```python\nprint('hello')\n```"
    expected = "<p>Here is some code:</p>\n<pre><code>print(&#x27;hello&#x27;)</code></pre>"
    assert markdown_to_html(text) == expected


def test_strip_markdown():
    text = "# Header\nThis is **bold** text."
    expected = "Header\nThis is bold text."
    assert strip_markdown(text) == expected
