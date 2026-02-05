#!/usr/bin/env python3
"""
Release Helper Script
---------------------
Analyzes git history to suggest a semantic version bump, updates setup.py,
and helps with tagging/committing.

Usage:
    python tools/release.py
"""

import os
import re
import sys
import subprocess
from pathlib import Path

# Try to use rich for pretty output, fallback if not available
try:
    from rich.console import Console
    from rich.prompt import Confirm, Prompt
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:
    class Console:
        def print(self, *args, **kwargs): print(*args)
        def rule(self, *args, **kwargs): print('-' * 40)
    class Confirm:
        @staticmethod
        def ask(text): return input(f"{text} (y/n): ").lower().startswith('y')
    class Prompt:
        @staticmethod
        def ask(text, default=None): return input(f"{text} [{default}]: ") or default
    class Panel:
        def __init__(self, *args, **kwargs): pass
    class Table:
        def add_column(self, *args): pass
        def add_row(self, *args): pass
    console = Console()

VERSION_PY_PATH = Path("src/version.py")

def run_command(cmd):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return None

def get_current_version():
    """Extract version from src/version.py."""
    if not VERSION_PY_PATH.exists():
        console.print("[red]Error: src/version.py not found![/red]")
        sys.exit(1)
    
    content = VERSION_PY_PATH.read_text(encoding='utf-8')
    match = re.search(r'__version__\s*=\s*["\']([^"\"]+)["\"]', content)
    if match:
        return match.group(1)
    return None

def get_last_tag():
    """Get the latest git tag."""
    return run_command("git describe --tags --abbrev=0")

def get_commits_since(tag):
    """Get list of commits since a tag."""
    range_spec = f"{tag}..HEAD" if tag else "HEAD"
    log_output = run_command(f"git log {range_spec} --pretty=format:\"%s\" ")
    if not log_output:
        return []
    return log_output.split('\n')

def analyze_changes(commits):
    """Analyze commits to determine SemVer bump."""
    major = minor = patch = 0
    
    for commit in commits:
        commit = commit.lower()
        if "breaking change" in commit or ":" in commit:
            major += 1
        elif commit.startswith("feat"):
            minor += 1
        elif commit.startswith("fix"):
            patch += 1
        # refactor, chore, docs, style usually don't trigger bumps, or trigger patch
            
    return major, minor, patch

def bump_version(current_ver, major_bump, minor_bump, patch_bump):
    """Calculate new version."""
    try:
        # Handle "v" prefix if present in version.py (though it shouldn't be there usually)
        clean_ver = current_ver.lstrip('v')
        parts = [int(p) for p in clean_ver.split('.')]
        while len(parts) < 3: parts.append(0)
        
        major, minor, patch = parts[:3]
        
        if major_bump > 0:
            major += 1
            minor = 0
            patch = 0
            reason = "Major (Breaking Changes)"
        elif minor_bump > 0:
            minor += 1
            patch = 0
            reason = "Minor (New Features)"
        else:
            patch += 1
            reason = "Patch (Bug Fixes/Other)"
            
        return f"{major}.{minor}.{patch}", reason
    except Exception as e:
        console.print(f"[red]Error parsing version '{current_ver}': {e}[/red]")
        return None, None

def update_version_py(new_version):
    """Update src/version.py with the new version."""
    content = VERSION_PY_PATH.read_text(encoding='utf-8')
    # Robust regex to find version line
    new_content = re.sub(
        r'(__version__\s*=\s*["\"])([^"\"]*)(["\"])',
        f'\g<1>{new_version}\g<3>',
        content
    )
    
    if content == new_content:
        console.print("[red]Could not update src/version.py. Pattern not found.[/red]")
        return False
        
    VERSION_PY_PATH.write_text(new_content, encoding='utf-8')
    return True

def main():
    console.rule("[bold blue]AIPromptBridge Release Helper[/bold blue]")
    
    # 1. Get Current Context
    current_version = get_current_version()
    last_tag = get_last_tag()
    
    if not current_version:
        console.print("[red]Could not determine current version from src/version.py[/red]")
        return

    console.print(f"Current src/version.py version: [bold cyan]{current_version}[/bold cyan]")
    console.print(f"Last Git Tag: [bold cyan]{last_tag or 'None'}[/bold cyan]")
    
    # 2. Analyze Commits
    commits = get_commits_since(last_tag)
    if not commits:
        console.print("[yellow]No new commits found since last tag.[/yellow]")
        if not Confirm.ask("Do you want to force a release anyway?"):
            return

    major_c, minor_c, patch_c = analyze_changes(commits)
    
    # Display Commit Summary
    if "Table" in globals():
        table = Table(title="Commits since last tag")
        table.add_column("Count", style="magenta")
        table.add_column("Type", style="green")
        table.add_row(str(major_c), "Breaking Changes")
        table.add_row(str(minor_c), "Features")
        table.add_row(str(patch_c), "Fixes")
        table.add_row(str(len(commits) - major_c - minor_c - patch_c), "Other (Refactor, Chore, etc)")
        console.print(table)
    
    # 3. Suggest Version
    next_version, reason = bump_version(current_version, major_c, minor_c, patch_c)
    
    console.print(f"\nSuggestion: [bold green]v{next_version}[/bold green] ({reason})")
    
    # 4. User Decision
    target_version = Prompt.ask("Enter release version", default=next_version)
    if not target_version:
        console.print("Cancelled.")
        return

    # Ensure clean version string for python
    clean_version = target_version.lstrip('v')
    
    if Confirm.ask(f"Update src/version.py to version {clean_version}?"):
        if update_version_py(clean_version):
            console.print("[green]Updated src/version.py successfully.[/green]")
        else:
            return

    # 5. Git Operations
    console.rule("[bold blue]Git Operations[/bold blue]")
    
    if Confirm.ask("Commit 'src/version.py' change?"):
        run_command(f"git add src/version.py")
        run_command(f"git commit -m \"chore(release): bump version to {clean_version}\" ")
        console.print("[green]Committed.[/green]")
    
    tag_name = f"v{clean_version}"
    if Confirm.ask(f"Create git tag '{tag_name}'?"):
        run_command(f"git tag {tag_name}")
        console.print(f"[green]Tag {tag_name} created.[/green]")
        
        if Confirm.ask("Push changes and tag to origin?"):
            console.print("[dim]Running: git push && git push --tags[/dim]")
            run_command("git push")
            run_command("git push --tags")
            console.print("[bold green]Pushed to origin. GitHub Action should be triggerable now![/bold green]")

if __name__ == "__main__":
    main()
