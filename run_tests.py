#!/usr/bin/env python3
"""
AIPromptBridge Test & Quality Suite Runner.
Consolidates Ruff check, Ruff format check, and Pytest into a single command.
"""

import subprocess
import sys


def run_command(command, description):
    print(f"\n=== Running {description} ===")
    print(f"Command: {' '.join(command)}")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"❌ {description} failed!")
        return False
    print(f"✅ {description} passed.")
    return True


def main():
    success = True

    # 1. Ruff lint check & auto-fix
    success &= run_command(["ruff", "check", "--fix", "."], "Linter (Ruff check with auto-fix)")

    # 2. Ruff formatting auto-apply
    success &= run_command(["ruff", "format", "."], "Formatter auto-apply (Ruff format)")

    # 3. Unit tests with Pytest
    success &= run_command(["pytest"], "Unit tests (Pytest)")

    if not success:
        print("\n❌ Some checks or tests failed!")
        sys.exit(1)

    print("\n🎉 All quality checks and unit tests passed successfully!")


if __name__ == "__main__":
    main()
