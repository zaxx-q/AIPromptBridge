"""Unit tests for platform-aware GitHub release asset selection."""

from __future__ import annotations

import src.updater as updater


def test_select_release_asset_windows_prefers_windows_zip(monkeypatch):
    monkeypatch.setattr("src.platform.detect.is_windows", lambda: True)
    monkeypatch.setattr("src.platform.detect.is_linux", lambda: False)

    assets = [
        {
            "name": "AIPromptBridge-v1.0.0-linux-x86_64.tar.gz",
            "browser_download_url": "https://example/linux.tgz",
            "size": 10,
        },
        {
            "name": "AIPromptBridge-v1.0.0-windows-x86_64.zip",
            "browser_download_url": "https://example/win.zip",
            "size": 20,
        },
        {
            "name": "AIPromptBridge-v1.0.0.zip",
            "browser_download_url": "https://example/legacy.zip",
            "size": 15,
        },
    ]
    url, size, name = updater._select_release_asset(assets)
    assert name == "AIPromptBridge-v1.0.0-windows-x86_64.zip"
    assert url == "https://example/win.zip"
    assert size == 20


def test_select_release_asset_linux_prefers_linux_tarball(monkeypatch):
    monkeypatch.setattr("src.platform.detect.is_windows", lambda: False)
    monkeypatch.setattr("src.platform.detect.is_linux", lambda: True)

    assets = [
        {
            "name": "AIPromptBridge-v1.0.0-windows-x86_64.zip",
            "browser_download_url": "https://example/win.zip",
            "size": 20,
        },
        {
            "name": "AIPromptBridge-v1.0.0-linux-x86_64.tar.gz",
            "browser_download_url": "https://example/linux.tgz",
            "size": 11,
        },
    ]
    url, size, name = updater._select_release_asset(assets)
    assert name == "AIPromptBridge-v1.0.0-linux-x86_64.tar.gz"
    assert url.endswith("linux.tgz")
    assert size == 11


def test_supports_in_place_update(monkeypatch):
    """In-place update is supported for compiled installs on any platform."""
    monkeypatch.setattr(updater, "is_compiled", lambda: True)
    assert updater._supports_in_place_update() is True

    monkeypatch.setattr(updater, "is_compiled", lambda: False)
    assert updater._supports_in_place_update() is False
