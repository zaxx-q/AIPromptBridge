"""Pytest wrapper that runs the standalone self-update test suite as a subprocess."""

import subprocess
import sys

import pytest


@pytest.mark.slow
def test_self_update_suite():
    """Run the standalone self-update test suite and verify it passes."""
    result = subprocess.run(
        [sys.executable, "test/self_update_suite.py"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    assert result.returncode == 0, f"Self-update test suite failed:\n{result.stdout}\n{result.stderr}"
