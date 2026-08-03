#!/usr/bin/env python3
"""Tests for AttachmentManager path resolution and cross-platform attachment compatibility."""

from pathlib import Path

from src.attachment_manager import AttachmentManager, resolve_attachment_path
from src.session_manager import ChatSession
from src.utils import normalize_path_str, resolve_file_path


class TestAttachmentManager:
    """Test AttachmentManager path resolution and cross-platform behavior."""

    def test_resolve_path_forward_slash(self, tmp_path, monkeypatch):
        """Test resolve_path with forward slashes."""
        test_dir = tmp_path / "session_attachments" / "999"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "0_test_img.webp"
        test_file.write_text("fake_image_data")

        # Set CWD to tmp_path during test
        monkeypatch.chdir(tmp_path)

        rel_path = "session_attachments/999/0_test_img.webp"
        resolved = AttachmentManager.resolve_path(rel_path)
        assert resolved.exists()
        assert resolved.as_posix() == rel_path

    def test_resolve_path_windows_backslashes(self, tmp_path, monkeypatch):
        """Test resolve_path resolves paths saved with Windows backslashes on Linux/POSIX."""
        test_dir = tmp_path / "session_attachments" / "570"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "0_1780730488_image.webp"
        test_file.write_text("fake_image_data")

        monkeypatch.chdir(tmp_path)

        # Windows style path
        win_path = r"session_attachments\570\0_1780730488_image.webp"
        resolved = AttachmentManager.resolve_path(win_path)
        assert resolved.exists()
        assert resolved == Path("session_attachments/570/0_1780730488_image.webp")

    def test_resolve_path_cross_machine_absolute(self, tmp_path, monkeypatch):
        """Test resolve_path handles cross-machine absolute paths containing session_attachments."""
        test_dir = tmp_path / "session_attachments" / "561"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "0_1777546691_image.webp"
        test_file.write_text("fake_image_data")

        monkeypatch.chdir(tmp_path)

        # Windows absolute path from another machine
        win_abs_path = (
            r"C:\Users\OldUser\AppData\Roaming\AIPromptBridge\session_attachments\561\0_1777546691_image.webp"
        )
        resolved = AttachmentManager.resolve_path(win_abs_path)
        assert resolved.exists()
        assert resolved == Path("session_attachments/561/0_1777546691_image.webp")

    def test_resolve_attachment_path_helper(self, tmp_path, monkeypatch):
        """Test resolve_attachment_path module-level helper."""
        test_dir = tmp_path / "session_attachments" / "100"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "file.txt"
        test_file.write_text("hello")

        monkeypatch.chdir(tmp_path)

        resolved = resolve_attachment_path(r"session_attachments\100\file.txt")
        assert resolved.exists()

    def test_session_manager_attachment_path_normalization(self):
        """Test that ChatSession.from_dict and add_message normalize backslashes to forward slashes."""
        data = {
            "session_id": 123,
            "origin": "chat",
            "messages": [
                {
                    "role": "user",
                    "content": "Look at this",
                    "attachments": [
                        {"path": r"session_attachments\123\0_170000_image.webp", "mime_type": "image/webp"}
                    ],
                }
            ],
        }

        session = ChatSession.from_dict(data)
        assert session.messages[0]["attachments"][0]["path"] == "session_attachments/123/0_170000_image.webp"

        # Test add_message
        session2 = ChatSession(session_id=124)
        session2.add_message(
            "user",
            "Test",
            attachments=[{"path": r"session_attachments\124\1_170000_image.webp", "mime_type": "image/webp"}],
        )
        assert session2.messages[0]["attachments"][0]["path"] == "session_attachments/124/1_170000_image.webp"

    def test_utils_normalize_path_str_and_resolve_file_path(self, tmp_path, monkeypatch):
        """Test central normalize_path_str and resolve_file_path functions in src.utils."""
        assert normalize_path_str(r"folder\subfolder\file.txt") == "folder/subfolder/file.txt"
        assert normalize_path_str(Path("folder/file.txt")) == "folder/file.txt"
        assert normalize_path_str(None) is None

        # Test resolve_file_path
        test_dir = tmp_path / "custom_anchor" / "sub"
        test_dir.mkdir(parents=True)
        test_file = test_dir / "data.csv"
        test_file.write_text("a,b,c")

        monkeypatch.chdir(tmp_path)

        resolved = resolve_file_path(r"C:\MyMachine\custom_anchor\sub\data.csv", anchor_dir="custom_anchor")
        assert resolved.exists()
        assert resolved == Path("custom_anchor/sub/data.csv")

    def test_resolve_file_path_traversal_protection(self, tmp_path, monkeypatch):
        """Test path traversal attempt outside CWD is blocked by resolve_file_path."""
        monkeypatch.chdir(tmp_path)
        outside_file = tmp_path.parent / "outside_secret.txt"
        outside_file.write_text("secret")

        try:
            # Traversal path attempting to escape
            traversal_path = f"session_attachments/../../{outside_file.name}"
            resolved = resolve_file_path(traversal_path)
            # Should not resolve to the outside file because it escapes CWD
            assert not (resolved.exists() and resolved.resolve() == outside_file.resolve())
        finally:
            if outside_file.exists():
                outside_file.unlink()
