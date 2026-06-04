"""
Centralized Rich Console Configuration
"""

try:
    from rich import print as rprint
    from rich.align import Align
    from rich.box import DOUBLE, HEAVY, ROUNDED
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme

    # Custom AIPromptBridge Theme
    custom_theme = Theme({
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "highlight": "magenta",
        "dim": "dim white",
        "header": "bold white on blue",
        "key": "bold cyan",
        "value": "yellow",
        "panel.border": "blue",
        "code": "bold white on black",
        "timestamp": "dim white",
    })

    console = Console(theme=custom_theme)
    HAVE_RICH = True

    def print_panel(content, title=None, style="blue", border_style="blue", subtitle=None):
        """Helper to print a uniform panel"""
        if isinstance(content, str):
            content = Text.from_markup(content)

        console.print(Panel(
            content,
            title=title,
            subtitle=subtitle,
            style=style,
            border_style=border_style,
            box=ROUNDED,
            expand=False
        ))

    def print_success(msg):
        console.print(f"[success]✅ {msg}[/success]")

    def print_error(msg):
        console.print(f"[error]❌ {msg}[/error]")

    def print_warning(msg):
        console.print(f"[warning]⚠️  {msg}[/warning]")

    def print_info(msg):
        console.print(f"[info]ℹ️  {msg}[/info]")

    def print_step(msg):
        console.print(f"[bold blue]Step:[/bold blue] {msg}")

except ImportError:
    HAVE_RICH = False

    # Fallback mock class
    class MockConsole:
        def print(self, *args, **kwargs):
            if args:
                print(*args)
            elif 'renderable' in kwargs:
                print(kwargs['renderable'])
            else:
                print()

        def input(self, prompt=""):
            return input(prompt)

        def status(self, *args, **kwargs):
            class MockStatus:
                def __enter__(self): pass
                def __exit__(self, exc_type, exc_val, exc_tb): pass
            return MockStatus()

    class MockPanel:
        def __init__(self, renderable, **kwargs):
            self.renderable = renderable

        def __str__(self):
            return str(self.renderable)

    class MockTable:
        def __init__(self, **kwargs):
            self.rows = []

        def add_column(self, *args, **kwargs): pass
        def add_row(self, *args): self.rows.append(args)

    console = MockConsole()
    Panel = MockPanel
    Table = MockTable
    Markdown = str
    Text = str
    rprint = print

    def print_panel(content, title=None, **kwargs):
        print("-" * 60)
        if title: print(f" {title} ")
        print("-" * 60)
        print(content)
        print("-" * 60)

    def print_success(msg): print(f"✅ {msg}")
    def print_error(msg): print(f"❌ {msg}")
    def print_warning(msg): print(f"⚠️  {msg}")
    def print_info(msg): print(f"ℹ️  {msg}")
    def print_step(msg): print(f"Step: {msg}")
