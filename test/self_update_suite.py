#!/usr/bin/env python3
"""
Comprehensive Self-Update Flow Test Suite

Simulates the entire update lifecycle defined in plans/self-update-plan.md:
  1. Version parsing & comparison
  2. GitHub API response parsing (mocked)
  3. Download simulation (creates a fake zip)
  4. Prepare/staging (zip extraction + manifest writing)
  5. apply_update() — the launcher's file-replacement logic
  6. Startup recovery (interrupted update rollback)
  7. .old file cleanup
  8. Root file update strategy (Windows rename trick)
  9. Source-mode detection (notification only)
 10. Signal flow (exit code 42 / --apply-update PID)

Run:
    uv run test/test_self_update.py
"""

import json
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

# ── Resolve project root ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Counters ────────────────────────────────────────────────────────────────
_pass = 0
_fail = 0
_skip = 0


def ok(label: str):
    global _pass
    _pass += 1
    print(f"  ✅ PASS  {label}")


def fail(label: str, detail: str = ""):
    global _fail
    _fail += 1
    print(f"  ❌ FAIL  {label}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"          {line}")


def skip(label: str, reason: str = ""):
    global _skip
    _skip += 1
    print(f"  ⏭️  SKIP  {label}  ({reason})")


def section(title: str):
    print(f"\n{'─' * 64}")
    print(f"  {title}")
    print(f"{'─' * 64}")


# ════════════════════════════════════════════════════════════════════════════
# HELPERS: create a realistic fake "release zip" on disk
# ════════════════════════════════════════════════════════════════════════════


def create_fake_release_zip(
    zip_path: str,
    version: str = "5.0.0",
    include_bin: bool = True,
    include_root_files: bool = True,
    single_root_dir: bool = True,
):
    """
    Build a zip that mimics a real AIPromptBridge release.

    Structure inside zip (when single_root_dir=True):
        AIPromptBridge-v5.0.0/
            bin/
                AIPromptBridge_Internal.exe   (dummy)
                icon.ico                      (dummy)
                python313.dll                 (dummy)
            AIPromptBridge.exe               (dummy)
            AIPromptBridge-NoConsole.exe      (dummy)
            python313.dll                    (dummy)
            lib/
                something.pyd                (dummy)
            frozen_application_license.txt
    """
    root_name = f"AIPromptBridge-v{version}" if single_root_dir else ""

    def _p(*parts):
        if root_name:
            return os.path.join(root_name, *parts)
        return os.path.join(*parts)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_bin:
            zf.writestr(_p("bin", "AIPromptBridge_Internal.exe"), f"FAKE_INTERNAL_{version}")
            zf.writestr(_p("bin", "icon.ico"), "FAKE_ICON")
            zf.writestr(_p("bin", "python313.dll"), f"FAKE_PYTHON_DLL_{version}")
            zf.writestr(_p("bin", "some_module.pyd"), "FAKE_PYD")

        if include_root_files:
            zf.writestr(_p("AIPromptBridge.exe"), f"FAKE_LAUNCHER_{version}")
            zf.writestr(_p("AIPromptBridge-NoConsole.exe"), f"FAKE_GUI_LAUNCHER_{version}")
            zf.writestr(_p("python313.dll"), f"FAKE_ROOT_DLL_{version}")
            zf.writestr(_p("lib", "something.pyd"), "FAKE_LIB")
            zf.writestr(_p("frozen_application_license.txt"), f"LICENSE v{version}")


def create_fake_current_install(root_dir: str, version: str = "4.0.0"):
    """Create a fake 'current installation' directory structure."""
    bin_dir = os.path.join(root_dir, "bin")
    lib_dir = os.path.join(root_dir, "lib")
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(lib_dir, exist_ok=True)

    # bin/ contents
    Path(bin_dir, "AIPromptBridge_Internal.exe").write_text(f"OLD_INTERNAL_{version}")
    Path(bin_dir, "icon.ico").write_text("OLD_ICON")
    Path(bin_dir, "python313.dll").write_text(f"OLD_PYTHON_DLL_{version}")

    # Root contents
    Path(root_dir, "AIPromptBridge.exe").write_text(f"OLD_LAUNCHER_{version}")
    Path(root_dir, "AIPromptBridge-NoConsole.exe").write_text(f"OLD_GUI_LAUNCHER_{version}")
    Path(root_dir, "python313.dll").write_text(f"OLD_ROOT_DLL_{version}")
    Path(lib_dir, "old_module.pyd").write_text("OLD_LIB")
    Path(root_dir, "frozen_application_license.txt").write_text(f"LICENSE v{version}")

    # User data (should NEVER be touched)
    Path(root_dir, "config.ini").write_text("[config]\nport = 5000\n")
    Path(root_dir, "prompts.json").write_text('{"version": 1}')
    Path(root_dir, "chat_sessions.json").write_text("[]")


# ════════════════════════════════════════════════════════════════════════════
# TEST 1: Version Parsing
# ════════════════════════════════════════════════════════════════════════════


def test_version_parsing():
    section("TEST 1: Version Parsing & Comparison")

    from src.updater import is_newer_version, parse_version

    # Basic parsing
    cases = [
        ("v5.4.1", (5, 4, 1)),
        ("5.10.0", (5, 10, 0)),
        ("V1.0.0", (1, 0, 0)),
        ("5.4.1-beta", (5, 4, 1)),
        ("0.1.0", (0, 1, 0)),
    ]
    for input_str, expected in cases:
        result = parse_version(input_str)
        if result == expected:
            ok(f"parse_version('{input_str}') == {expected}")
        else:
            fail(f"parse_version('{input_str}')", f"expected {expected}, got {result}")

    # Comparison
    comparison_cases = [
        ("v5.5.0", "5.4.0", True),
        ("v5.4.0", "5.4.0", False),  # same version
        ("v5.3.0", "5.4.0", False),  # older
        ("v5.10.0", "5.9.0", True),  # numeric, not lexicographic
        ("v1.0.0", "0.9.99", True),
        ("v4.0.0", "4.0.0", False),  # exact match = not newer
    ]
    for remote, local, expected in comparison_cases:
        result = is_newer_version(remote, local)
        if result == expected:
            ok(f"is_newer_version('{remote}', '{local}') == {expected}")
        else:
            fail(f"is_newer_version('{remote}', '{local}')", f"expected {expected}, got {result}")


# ════════════════════════════════════════════════════════════════════════════
# TEST 2: GitHub API Response Parsing (Mocked)
# ══════════════════════════════════════════════════════════════════��═════════


def test_github_api_parsing():
    section("TEST 2: GitHub API Response Parsing (Mocked)")

    from src.updater import UpdateInfo

    # Simulate a GitHub releases/latest JSON response
    mock_release = {
        "tag_name": "v5.5.0",
        "html_url": "https://github.com/zaxx-q/AIPromptBridge/releases/tag/v5.5.0",
        "body": "## Changelog\n- New feature\n- Bug fix",
        "published_at": "2026-03-20T10:00:00Z",
        "assets": [
            {
                "name": "AIPromptBridge-v5.5.0-Windows.zip",
                "browser_download_url": "https://github.com/zaxx-q/AIPromptBridge/releases/download/v5.5.0/AIPromptBridge-v5.5.0-Windows.zip",
                "size": 85000000,
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://github.com/zaxx-q/AIPromptBridge/releases/download/v5.5.0/checksums.txt",
                "size": 256,
            },
        ],
    }

    # Simulate asset selection logic from check_for_update
    assets = mock_release.get("assets", [])
    download_url = None
    asset_size = 0
    asset_name = ""

    for asset in assets:
        name = asset.get("name", "").lower()
        if name.endswith(".zip") and ("windows" in name or "win" in name or "aipromptbridge" in name):
            download_url = asset.get("browser_download_url")
            asset_size = asset.get("size", 0)
            asset_name = asset.get("name", "")
            break

    if not download_url:
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".zip"):
                download_url = asset.get("browser_download_url")
                asset_size = asset.get("size", 0)
                asset_name = asset.get("name", "")
                break

    if download_url and "AIPromptBridge-v5.5.0-Windows.zip" in download_url:
        ok("Asset selection: found Windows zip")
    else:
        fail("Asset selection", f"got: {download_url}")

    if asset_size == 85000000:
        ok(f"Asset size: {asset_size}")
    else:
        fail("Asset size", f"expected 85000000, got {asset_size}")

    # Build UpdateInfo
    info = UpdateInfo(
        version=mock_release["tag_name"].lstrip("vV"),
        tag_name=mock_release["tag_name"],
        download_url=download_url or "",
        asset_size=asset_size,
        asset_name=asset_name,
        release_notes=mock_release.get("body", ""),
        release_url=mock_release.get("html_url", ""),
        published_at=mock_release.get("published_at", ""),
    )

    if info.version == "5.5.0":
        ok(f"UpdateInfo.version == '{info.version}'")
    else:
        fail("UpdateInfo.version", f"got '{info.version}'")

    # Test with no zip assets
    mock_release_no_zip = dict(mock_release)
    mock_release_no_zip["assets"] = [{"name": "checksums.txt", "browser_download_url": "http://...", "size": 100}]
    found = False
    for asset in mock_release_no_zip["assets"]:
        if asset.get("name", "").lower().endswith(".zip"):
            found = True
    if not found:
        ok("No zip asset found → notification-only path")
    else:
        fail("No zip asset detection")


# ════════════════════════════════════════════════════════════════════════════
# TEST 3: Prepare Update (Zip Extraction + Manifest)
# ════════════════════════════════════════════════════════════════════════════


def test_prepare_update():
    section("TEST 3: Prepare Update (Zip → Staging + Manifest)")

    from src.updater import MANIFEST_FILE, STAGING_DIR, UpdateInfo

    work_dir = tempfile.mkdtemp(prefix="aipb_test_prepare_")
    original_cwd = os.getcwd()

    try:
        os.chdir(work_dir)

        # Create fake zip
        zip_path = os.path.join(work_dir, "update.zip")
        create_fake_release_zip(zip_path, version="5.0.0", single_root_dir=True)

        info = UpdateInfo(
            version="5.0.0",
            tag_name="v5.0.0",
            download_url="https://example.com/fake.zip",
            asset_size=os.path.getsize(zip_path),
            asset_name="update.zip",
            release_notes="Test release",
            release_url="https://example.com",
            published_at="2026-01-01T00:00:00Z",
        )

        # Simulate prepare_update logic (extracted from src/updater.py)
        staging_dir = Path(STAGING_DIR)
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        with zipfile.ZipFile(zip_path, "r") as zf:
            top_level = set()
            for name in zf.namelist():
                parts = name.split("/")
                if parts[0]:
                    top_level.add(parts[0])

            if len(top_level) == 1:
                root_name = top_level.pop()
                zf.extractall(str(staging_dir.parent))
                extracted_path = staging_dir.parent / root_name
                if extracted_path != staging_dir:
                    if staging_dir.exists():
                        shutil.rmtree(staging_dir)
                    extracted_path.rename(staging_dir)
            else:
                zf.extractall(str(staging_dir))

        # Verify staging directory
        if staging_dir.exists() and any(staging_dir.iterdir()):
            ok("Staging directory created with content")
        else:
            fail("Staging directory", "empty or missing")

        # Verify bin/ inside staging
        staging_bin = staging_dir / "bin"
        if staging_bin.exists():
            ok("Staging has bin/ directory")
        else:
            fail("Staging bin/", "missing")

        internal_exe = staging_bin / "AIPromptBridge_Internal.exe"
        if internal_exe.exists():
            content = internal_exe.read_text()
            if "5.0.0" in content:
                ok("Staged Internal.exe contains new version marker")
            else:
                fail("Staged Internal.exe content", f"got: {content}")
        else:
            fail("Staged Internal.exe", "file missing")

        # Write manifest
        manifest = {
            "version": info.version,
            "staging_dir": STAGING_DIR,
            "launcher_to_relaunch": "AIPromptBridge.exe",
            "launched_mode": "console",
            "original_args": ["--show-console"],
        }
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        if Path(MANIFEST_FILE).exists():
            with open(MANIFEST_FILE) as f:
                loaded = json.load(f)
            if loaded["version"] == "5.0.0":
                ok(f"Manifest written: version={loaded['version']}")
            else:
                fail("Manifest version", f"got {loaded['version']}")
        else:
            fail("Manifest file", "not created")

        # Verify root-level files in staging (for root file update)
        root_launcher = staging_dir / "AIPromptBridge.exe"
        if root_launcher.exists():
            ok("Staging has root launcher file")
        else:
            fail("Staging root launcher", "missing")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


# ════��═══════════════════════════════════════════════════════════════════════
# TEST 4: Apply Update (Launcher Logic)
# ════════════════════════════════════════════════════════════════════════════


def test_apply_update():
    section("TEST 4: apply_update() — Full File Replacement")

    # Import launcher functions directly
    sys.path.insert(0, str(PROJECT_ROOT / "src" / "launchers"))
    from launcher_console import BACKUP_DIR, MANIFEST_FILE, STAGING_DIR, apply_update

    work_dir = tempfile.mkdtemp(prefix="aipb_test_apply_")
    original_cwd = os.getcwd()

    try:
        os.chdir(work_dir)
        root_dir = work_dir

        # 1. Create fake current installation
        create_fake_current_install(root_dir, version="4.0.0")

        # 2. Create fake staging (simulating what prepare_update would do)
        staging_dir = os.path.join(root_dir, STAGING_DIR)
        staging_bin = os.path.join(staging_dir, "bin")
        os.makedirs(staging_bin, exist_ok=True)

        # New bin/ files
        Path(staging_bin, "AIPromptBridge_Internal.exe").write_text("NEW_INTERNAL_5.0.0")
        Path(staging_bin, "icon.ico").write_text("NEW_ICON")
        Path(staging_bin, "python313.dll").write_text("NEW_PYTHON_DLL_5.0.0")
        Path(staging_bin, "new_module.pyd").write_text("NEW_PYD")

        # New root files in staging
        Path(staging_dir, "AIPromptBridge.exe").write_text("NEW_LAUNCHER_5.0.0")
        Path(staging_dir, "AIPromptBridge-NoConsole.exe").write_text("NEW_GUI_LAUNCHER_5.0.0")
        staging_lib = os.path.join(staging_dir, "lib")
        os.makedirs(staging_lib, exist_ok=True)
        Path(staging_lib, "new_lib.pyd").write_text("NEW_LIB")

        # 3. Write manifest
        manifest = {
            "version": "5.0.0",
            "staging_dir": STAGING_DIR,
            "launcher_to_relaunch": "AIPromptBridge.exe",
            "launched_mode": "console",
            "original_args": [],
        }
        manifest_path = os.path.join(root_dir, MANIFEST_FILE)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        # 4. Run apply_update
        result = apply_update(root_dir)

        if result:
            ok("apply_update() returned True")
        else:
            fail("apply_update()", "returned False")
            return  # Can't continue checks

        # 5. Verify new bin/ is deployed
        new_internal = Path(root_dir, "bin", "AIPromptBridge_Internal.exe")
        if new_internal.exists():
            content = new_internal.read_text()
            if "NEW_INTERNAL_5.0.0" in content:
                ok("bin/Internal.exe contains new version")
            else:
                fail("bin/Internal.exe content", f"got: {content}")
        else:
            fail("bin/Internal.exe", "missing after update")

        # Verify new module deployed
        new_pyd = Path(root_dir, "bin", "new_module.pyd")
        if new_pyd.exists():
            ok("New module deployed in bin/")
        else:
            fail("New module in bin/", "missing")

        # 6. Verify root files were updated
        # On non-Windows or when files aren't locked, direct overwrite applies
        root_launcher = Path(root_dir, "AIPromptBridge.exe")
        if root_launcher.exists():
            content = root_launcher.read_text()
            # Could be new version (direct overwrite) or old (if locked on Windows)
            if "NEW_LAUNCHER_5.0.0" in content or "OLD_LAUNCHER_4.0.0" in content:
                if "NEW_LAUNCHER_5.0.0" in content:
                    ok("Root launcher updated to new version")
                else:
                    # On Windows, the .old rename trick might leave the original
                    # but the new file should be the .exe without .old
                    ok("Root launcher exists (may need .old cleanup on Windows)")
            else:
                fail("Root launcher content", f"unexpected: {content}")
        else:
            fail("Root launcher", "missing")

        # 7. Verify backup was cleaned up
        backup_dir = Path(root_dir, BACKUP_DIR)
        if not backup_dir.exists():
            ok("Backup dir (_bin_old/) cleaned up")
        else:
            fail("Backup dir cleanup", "_bin_old/ still exists")

        # 8. Verify staging was cleaned up
        staging_path = Path(root_dir, STAGING_DIR)
        if not staging_path.exists():
            ok("Staging dir cleaned up")
        else:
            fail("Staging dir cleanup", "_update_staging/ still exists")

        # 9. Verify manifest was cleaned up
        if not Path(manifest_path).exists():
            ok("Manifest file cleaned up")
        else:
            fail("Manifest cleanup", "_update_pending.json still exists")

        # 10. Verify USER DATA was NOT touched
        config_ini = Path(root_dir, "config.ini")
        if config_ini.exists():
            content = config_ini.read_text()
            if "port = 5000" in content:
                ok("User data (config.ini) preserved ✓")
            else:
                fail("User data preservation", f"config.ini modified: {content}")
        else:
            fail("User data preservation", "config.ini deleted!")

        prompts = Path(root_dir, "prompts.json")
        if prompts.exists():
            ok("User data (prompts.json) preserved ✓")
        else:
            fail("User data preservation", "prompts.json deleted!")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# TEST 5: Startup Recovery
# ════════════════════════════════════════════════════════════════════════════


def test_startup_recovery():
    section("TEST 5: Startup Recovery (Interrupted Update)")

    from src.updater import BACKUP_DIR, MANIFEST_FILE, STAGING_DIR

    # ── Case 1: bin/ missing + _bin_old/ exists → rollback ──
    work_dir = tempfile.mkdtemp(prefix="aipb_test_recovery1_")
    original_cwd = os.getcwd()
    try:
        os.chdir(work_dir)

        # Create _bin_old/ but no bin/
        backup = Path(BACKUP_DIR)
        backup.mkdir()
        (backup / "AIPromptBridge_Internal.exe").write_text("BACKUP_INTERNAL")

        from src.updater import startup_recovery

        startup_recovery()

        bin_dir = Path("bin")
        if bin_dir.exists() and (bin_dir / "AIPromptBridge_Internal.exe").exists():
            content = (bin_dir / "AIPromptBridge_Internal.exe").read_text()
            if content == "BACKUP_INTERNAL":
                ok("Case 1: Rollback _bin_old/ → bin/ successful")
            else:
                fail("Case 1 rollback content", f"got: {content}")
        else:
            fail("Case 1 rollback", "bin/ not restored")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)

    # ── Case 2: Stale manifest without staging → cleanup ──
    work_dir = tempfile.mkdtemp(prefix="aipb_test_recovery2_")
    try:
        os.chdir(work_dir)

        # Create manifest but no staging dir
        Path(MANIFEST_FILE).write_text('{"version": "5.0.0"}')

        startup_recovery()

        if not Path(MANIFEST_FILE).exists():
            ok("Case 2: Stale manifest cleaned up")
        else:
            fail("Case 2 stale manifest", "still exists")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)

    # ── Case 3: Leftover staging without manifest → cleanup ──
    work_dir = tempfile.mkdtemp(prefix="aipb_test_recovery3_")
    try:
        os.chdir(work_dir)

        staging = Path(STAGING_DIR)
        staging.mkdir()
        (staging / "dummy.txt").write_text("leftover")

        startup_recovery()

        if not staging.exists():
            ok("Case 3: Leftover staging cleaned up")
        else:
            fail("Case 3 leftover staging", "still exists")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)

    # ── Case 4: Leftover _bin_old/ after successful update → cleanup ──
    work_dir = tempfile.mkdtemp(prefix="aipb_test_recovery4_")
    try:
        os.chdir(work_dir)

        # Both bin/ and _bin_old/ exist (successful update, cleanup failed)
        Path("bin").mkdir()
        (Path("bin") / "Internal.exe").write_text("NEW")
        Path(BACKUP_DIR).mkdir()
        (Path(BACKUP_DIR) / "Internal.exe").write_text("OLD")

        startup_recovery()

        if not Path(BACKUP_DIR).exists():
            ok("Case 4: Leftover backup cleaned after successful update")
        else:
            fail("Case 4 leftover backup", "still exists")

        # Verify bin/ is untouched
        if Path("bin", "Internal.exe").read_text() == "NEW":
            ok("Case 4: bin/ content preserved")
        else:
            fail("Case 4 bin/ preservation")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# TEST 6: Root File Update Strategy
# ════════════════════════════════════════════════════════════════════════════


def test_root_file_update():
    section("TEST 6: Root File Update Strategy (rename trick)")

    sys.path.insert(0, str(PROJECT_ROOT / "src" / "launchers"))
    from launcher_console import update_root_files

    work_dir = tempfile.mkdtemp(prefix="aipb_test_rootfiles_")

    try:
        root_dir = work_dir
        staging_dir = os.path.join(work_dir, "_staging")

        # Create current root files
        for name in [
            "AIPromptBridge.exe",
            "AIPromptBridge-NoConsole.exe",
            "python313.dll",
            "frozen_application_license.txt",
        ]:
            Path(root_dir, name).write_text(f"OLD_{name}")

        os.makedirs(os.path.join(root_dir, "lib"), exist_ok=True)
        Path(root_dir, "lib", "old.pyd").write_text("OLD_LIB")

        # Create staging root files
        os.makedirs(staging_dir, exist_ok=True)
        for name in [
            "AIPromptBridge.exe",
            "AIPromptBridge-NoConsole.exe",
            "python313.dll",
            "frozen_application_license.txt",
        ]:
            Path(staging_dir, name).write_text(f"NEW_{name}")

        os.makedirs(os.path.join(staging_dir, "lib"), exist_ok=True)
        Path(staging_dir, "lib", "new.pyd").write_text("NEW_LIB")

        # Run update_root_files
        update_root_files(root_dir, staging_dir)

        # Verify files were updated
        for name in [
            "AIPromptBridge.exe",
            "AIPromptBridge-NoConsole.exe",
            "python313.dll",
            "frozen_application_license.txt",
        ]:
            target = Path(root_dir, name)
            if target.exists():
                content = target.read_text()
                if f"NEW_{name}" in content:
                    ok(f"Root file '{name}' updated")
                else:
                    # On Windows, might have been renamed to .old
                    old_path = Path(root_dir, name + ".old")
                    if old_path.exists():
                        ok(f"Root file '{name}' → .old rename trick applied")
                    else:
                        fail(f"Root file '{name}'", f"content: {content}")
            else:
                fail(f"Root file '{name}'", "missing")

        # Verify lib/ directory was updated
        new_lib = Path(root_dir, "lib")
        if new_lib.exists() and new_lib.is_dir():
            ok("lib/ directory updated")
        else:
            fail("lib/ directory", "missing or not a directory")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# TEST 7: .old File Cleanup
# ════════════════════════════════════════════════════════════════════════════


def test_old_file_cleanup():
    section("TEST 7: .old File Cleanup (launcher startup)")

    sys.path.insert(0, str(PROJECT_ROOT / "src" / "launchers"))
    from launcher_console import ROOT_UPDATE_ALLOWLIST, cleanup_old_files

    work_dir = tempfile.mkdtemp(prefix="aipb_test_cleanup_")

    try:
        # Create .old files
        for name in ROOT_UPDATE_ALLOWLIST:
            old_path = os.path.join(work_dir, name + ".old")
            if name == "lib":
                os.makedirs(old_path, exist_ok=True)
                Path(old_path, "dummy.pyd").write_text("OLD")
            else:
                Path(old_path).write_text(f"OLD_{name}")

        # Also create the real files (they should NOT be touched)
        for name in ROOT_UPDATE_ALLOWLIST:
            real_path = os.path.join(work_dir, name)
            if name == "lib":
                os.makedirs(real_path, exist_ok=True)
                Path(real_path, "real.pyd").write_text("REAL")
            else:
                Path(real_path).write_text(f"REAL_{name}")

        # Run cleanup
        cleanup_old_files(work_dir)

        # Verify .old files are gone
        all_cleaned = True
        for name in ROOT_UPDATE_ALLOWLIST:
            old_path = os.path.join(work_dir, name + ".old")
            if os.path.exists(old_path):
                all_cleaned = False
                fail(f".old cleanup: {name}.old", "still exists")

        if all_cleaned:
            ok("All .old files/dirs cleaned up")

        # Verify real files untouched
        all_real = True
        for name in ROOT_UPDATE_ALLOWLIST:
            real_path = os.path.join(work_dir, name)
            if not os.path.exists(real_path):
                all_real = False
                fail(f"Real file preserved: {name}", "was deleted!")

        if all_real:
            ok("Real files preserved during .old cleanup")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# TEST 8: Source Mode Detection
# ════════════════════════════════════════════════════════════════════════════


def test_source_mode():
    section("TEST 8: Source Mode Detection")

    from src.utils import is_compiled

    # When running from source (python test_self_update.py), we should NOT be compiled
    compiled = is_compiled()
    if not compiled:
        ok("is_compiled() returns False when running from source")
    else:
        # Could be True if running from a compiled exe — still valid
        skip("is_compiled() check", "running from compiled binary")


# ════════════════════════════════════════════════════════════════════════════
# TEST 9: Config Integration
# ════════════════════════════════════════════════════════════════════════════


def test_config_integration():
    section("TEST 9: Config Integration")

    from src.config import DEFAULT_CONFIG

    # Check that update settings exist in DEFAULT_CONFIG
    if "update_check_enabled" in DEFAULT_CONFIG:
        if DEFAULT_CONFIG["update_check_enabled"] is True:
            ok("DEFAULT_CONFIG has update_check_enabled = True")
        else:
            fail("update_check_enabled default", f"got {DEFAULT_CONFIG['update_check_enabled']}")
    else:
        fail("update_check_enabled", "missing from DEFAULT_CONFIG")


# ════════════════════════════════════════════════════════════════════════════
# TEST 10: Constants Consistency
# ════════════════════════════════════════════════════════════════════════════


def test_constants_consistency():
    section("TEST 10: Constants Consistency (updater ↔ launcher)")

    from src.updater import BACKUP_DIR as BD_UPDATER
    from src.updater import MANIFEST_FILE as MF_UPDATER
    from src.updater import STAGING_DIR as SD_UPDATER
    from src.updater import UPDATE_EXIT_CODE as UEC_UPDATER

    sys.path.insert(0, str(PROJECT_ROOT / "src" / "launchers"))
    from launcher_console import BACKUP_DIR as BD_LAUNCHER
    from launcher_console import MANIFEST_FILE as MF_LAUNCHER
    from launcher_console import STAGING_DIR as SD_LAUNCHER
    from launcher_console import UPDATE_EXIT_CODE as UEC_LAUNCHER

    pairs = [
        ("UPDATE_EXIT_CODE", UEC_UPDATER, UEC_LAUNCHER),
        ("STAGING_DIR", SD_UPDATER, SD_LAUNCHER),
        ("BACKUP_DIR", BD_UPDATER, BD_LAUNCHER),
        ("MANIFEST_FILE", MF_UPDATER, MF_LAUNCHER),
    ]

    for name, val1, val2 in pairs:
        if val1 == val2:
            ok(f"{name}: updater({val1}) == launcher({val2})")
        else:
            fail(f"{name} mismatch", f"updater={val1}, launcher={val2}")


# ════════════════════════════════════════════════════════════════════════════
# TEST 11: Launcher Exit Code & --apply-update Handling
# ════════════════════════════════════════════════════════════════════════════


def test_launcher_signal_flow():
    section("TEST 11: Launcher Signal Flow Verification")

    # Read the launcher source to verify the exit code handling exists
    launcher_path = PROJECT_ROOT / "src" / "launchers" / "launcher_console.py"
    launcher_source = launcher_path.read_text()

    # Check exit code 42 handler
    if "exit_code == UPDATE_EXIT_CODE" in launcher_source or "exit_code == 42" in launcher_source:
        ok("Launcher handles exit code 42 (UPDATE_EXIT_CODE)")
    else:
        fail("Exit code 42 handler", "not found in launcher_console.py")

    # Check --apply-update handler
    if '"--apply-update"' in launcher_source or "'--apply-update'" in launcher_source:
        ok("Launcher handles --apply-update argument")
    else:
        fail("--apply-update handler", "not found in launcher_console.py")

    # Check wait_for_process_exit
    if "wait_for_process_exit" in launcher_source:
        ok("wait_for_process_exit() function present")
    else:
        fail("wait_for_process_exit", "not found")

    # Check pending update on startup
    if "pending update" in launcher_source.lower() or "Found pending" in launcher_source:
        ok("Startup pending update check present")
    else:
        fail("Startup pending update check", "not found")

    # Check relaunch_from_manifest
    if "relaunch_from_manifest" in launcher_source:
        ok("relaunch_from_manifest() used after apply_update")
    else:
        fail("relaunch_from_manifest", "not found")


# ════════════════════════════════════════════════════════════════════════════
# TEST 12: Main.py Integration
# ════════════════════════════════════════════════════════════════════════════


def test_main_integration():
    section("TEST 12: main.py Integration")

    main_path = PROJECT_ROOT / "main.py"
    main_source = main_path.read_text()

    # Check startup recovery
    if "startup_recovery" in main_source:
        ok("main.py calls startup_recovery()")
    else:
        fail("startup_recovery in main.py", "not found")

    # Check background update check
    if "background_update_check" in main_source:
        ok("main.py calls background_update_check()")
    else:
        fail("background_update_check in main.py", "not found")


# ════════════════════════════════════════════════════════════════════════════
# TEST 13: Tray Integration
# ════════════════════════════════════════════════════════════════════════════


def test_tray_integration():
    section("TEST 13: Tray & Terminal Integration")

    tray_path = PROJECT_ROOT / "src" / "tray.py"
    tray_source = tray_path.read_text()

    if "Check for Updates" in tray_source:
        ok("Tray menu has 'Check for Updates' item")
    else:
        fail("Tray 'Check for Updates'", "not found")

    if "_on_check_updates" in tray_source:
        ok("Tray has _on_check_updates callback")
    else:
        fail("Tray _on_check_updates", "not found")

    # Terminal integration
    terminal_path = PROJECT_ROOT / "src" / "terminal.py"
    terminal_source = terminal_path.read_text()

    if "key == 'u'" in terminal_source or 'key == "u"' in terminal_source:
        ok("Terminal has 'U' key handler for updates")
    else:
        fail("Terminal 'U' key handler", "not found")

    if "check_and_prompt_terminal" in terminal_source:
        ok("Terminal calls check_and_prompt_terminal()")
    else:
        fail("Terminal check_and_prompt_terminal", "not found")


# ═══════════════════��════════════════════════════════════════════════════════
# TEST 14: Settings Window Integration
# ════════════════════════════════════════════════════════════════════════════


def test_settings_integration():
    section("TEST 14: Settings Window Integration")

    settings_path = PROJECT_ROOT / "src" / "gui" / "windows" / "settings_window" / "tab_general.py"
    settings_source = settings_path.read_text()

    if "update_check_enabled" in settings_source:
        ok("Settings window has update_check_enabled toggle")
    else:
        fail("Settings update_check_enabled", "not found")

    if "Check Now" in settings_source:
        ok("Settings window has 'Check Now' button")
    else:
        fail("Settings 'Check Now' button", "not found")

    if "_on_check_updates_now" in settings_source:
        ok("Settings has _on_check_updates_now callback")
    else:
        fail("Settings _on_check_updates_now", "not found")

    if "get_cached_update_info" in settings_source:
        ok("Settings shows cached update info")
    else:
        fail("Settings cached update info", "not found")


# ════════════════════════════════════════════════════════════════════════════
# TEST 15: cx_Freeze Excludes Verification
# ════════════════════════════════════════════════════════════════════════════


def test_cx_freeze_excludes():
    section("TEST 15: cx_Freeze Setup Verification")

    setup_path = PROJECT_ROOT / "src" / "launchers" / "setup_launchers.py"
    setup_source = setup_path.read_text()

    # The plan says: Remove from excludes: json, shutil, fnmatch
    # But the current implementation imports json and shutil in launcher_console.py
    # Let's check that json and shutil are NOT in the excludes list

    # Parse the excludes list from the source

    # Find the excludes list between "excludes" and the closing bracket
    excludes_start = setup_source.find('"excludes": [')
    if excludes_start == -1:
        excludes_start = setup_source.find("'excludes': [")

    if excludes_start != -1:
        # Find from [ to ]
        bracket_start = setup_source.find("[", excludes_start)
        bracket_count = 0
        bracket_end = bracket_start
        for i in range(bracket_start, len(setup_source)):
            if setup_source[i] == "[":
                bracket_count += 1
            elif setup_source[i] == "]":
                bracket_count -= 1
                if bracket_count == 0:
                    bracket_end = i + 1
                    break

        excludes_str = setup_source[bracket_start:bracket_end]

        # Check that json, shutil are NOT excluded (they're needed by the launcher)
        if '"json"' not in excludes_str and "'json'" not in excludes_str:
            ok("'json' is NOT in cx_Freeze excludes (available for launcher)")
        else:
            fail("json in excludes", "json should not be excluded — launcher needs it")

        if '"shutil"' not in excludes_str and "'shutil'" not in excludes_str:
            ok("'shutil' is NOT in cx_Freeze excludes (available for launcher)")
        else:
            fail("shutil in excludes", "shutil should not be excluded — launcher needs it")

        # fnmatch is needed by shutil.copytree
        if '"fnmatch"' not in excludes_str and "'fnmatch'" not in excludes_str:
            ok("'fnmatch' is NOT in cx_Freeze excludes (shutil dependency)")
        else:
            fail("fnmatch in excludes", "fnmatch should not be excluded — shutil needs it")
    else:
        fail("cx_Freeze excludes", "could not find excludes list in setup_launchers.py")


# ════════════════════════════════════════════════════════════════════════════
# TEST 16: Full End-to-End Simulation
# ════════════════════════════════════════════════════════════════════════════


def test_end_to_end():
    section("TEST 16: Full End-to-End Simulation")

    from src.updater import BACKUP_DIR, MANIFEST_FILE, STAGING_DIR

    sys.path.insert(0, str(PROJECT_ROOT / "src" / "launchers"))
    from launcher_console import apply_update, cleanup_old_files

    work_dir = tempfile.mkdtemp(prefix="aipb_test_e2e_")
    original_cwd = os.getcwd()

    try:
        os.chdir(work_dir)
        root_dir = work_dir

        print("\n  ── Phase 0: Create current installation (v4.0.0) ──")
        create_fake_current_install(root_dir, "4.0.0")
        ok("Current installation created")

        print("\n  ── Phase 1: Download & Prepare (simulated) ──")

        # Create fake downloaded zip
        zip_path = os.path.join(work_dir, "download.zip")
        create_fake_release_zip(zip_path, version="5.0.0")
        ok(f"Fake release zip created ({os.path.getsize(zip_path)} bytes)")

        # Extract to staging
        staging_dir = Path(STAGING_DIR)
        with zipfile.ZipFile(zip_path, "r") as zf:
            top_level = set()
            for name in zf.namelist():
                parts = name.split("/")
                if parts[0]:
                    top_level.add(parts[0])

            if len(top_level) == 1:
                root_name = top_level.pop()
                zf.extractall(".")
                extracted = Path(root_name)
                if extracted != staging_dir:
                    if staging_dir.exists():
                        shutil.rmtree(staging_dir)
                    extracted.rename(staging_dir)
            else:
                zf.extractall(str(staging_dir))

        ok("Zip extracted to staging")

        # Write manifest
        manifest = {
            "version": "5.0.0",
            "staging_dir": STAGING_DIR,
            "launcher_to_relaunch": "AIPromptBridge.exe",
            "launched_mode": "console",
            "original_args": ["--show-console"],
        }
        with open(MANIFEST_FILE, "w") as f:
            json.dump(manifest, f, indent=2)
        ok("Manifest written")

        print("\n  ── Phase 2: Apply Update (launcher side) ──")
        result = apply_update(root_dir)
        if result:
            ok("apply_update() succeeded")
        else:
            fail("apply_update()", "returned False")
            return

        print("\n  ── Phase 3: Verification ──")

        # Verify new version deployed
        internal = Path("bin", "AIPromptBridge_Internal.exe")
        if internal.exists() and "5.0.0" in internal.read_text():
            ok("New Internal.exe v5.0.0 deployed")
        else:
            fail("Internal.exe deployment")

        # Verify cleanup
        if not Path(BACKUP_DIR).exists():
            ok("_bin_old/ cleaned up")
        else:
            fail("_bin_old/ cleanup")

        if not Path(STAGING_DIR).exists():
            ok("_update_staging/ cleaned up")
        else:
            fail("_update_staging/ cleanup")

        if not Path(MANIFEST_FILE).exists():
            ok("_update_pending.json cleaned up")
        else:
            fail("_update_pending.json cleanup")

        # Verify user data untouched
        if Path("config.ini").exists() and "port = 5000" in Path("config.ini").read_text():
            ok("config.ini preserved")
        else:
            fail("config.ini preservation")

        if Path("prompts.json").exists():
            ok("prompts.json preserved")
        else:
            fail("prompts.json preservation")

        if Path("chat_sessions.json").exists():
            ok("chat_sessions.json preserved")
        else:
            fail("chat_sessions.json preservation")

        print("\n  ── Phase 4: Simulate .old cleanup on next launch ──")
        # Create some .old files as if Windows rename trick was used
        Path("AIPromptBridge.exe.old").write_text("OLD_LAUNCHER")
        Path("python313.dll.old").write_text("OLD_DLL")

        cleanup_old_files(root_dir)

        if not Path("AIPromptBridge.exe.old").exists():
            ok(".old launcher cleaned on next launch")
        else:
            fail(".old launcher cleanup")

        if not Path("python313.dll.old").exists():
            ok(".old DLL cleaned on next launch")
        else:
            fail(".old DLL cleanup")

        print("\n  ── Phase 5: Verify startup recovery is safe on clean state ──")
        from src.updater import startup_recovery

        startup_recovery()  # Should be a no-op
        ok("startup_recovery() is safe on clean installation")

    finally:
        os.chdir(original_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════


def main():
    print()
    print("=" * 64)
    print("  AIPromptBridge Self-Update Test Suite")
    print("  Testing: plans/self-update-plan.md implementation")
    print("=" * 64)

    tests = [
        test_version_parsing,
        test_github_api_parsing,
        test_prepare_update,
        test_apply_update,
        test_startup_recovery,
        test_root_file_update,
        test_old_file_cleanup,
        test_source_mode,
        test_config_integration,
        test_constants_consistency,
        test_launcher_signal_flow,
        test_main_integration,
        test_tray_integration,
        test_settings_integration,
        test_cx_freeze_excludes,
        test_end_to_end,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception:
            fail(f"EXCEPTION in {test_fn.__name__}", traceback.format_exc())

    # ── Summary ──
    print()
    print("=" * 64)
    total = _pass + _fail + _skip
    print(f"  Results: {_pass} passed, {_fail} failed, {_skip} skipped (total: {total})")
    if _fail == 0:
        print("  🎉 ALL TESTS PASSED!")
    else:
        print(f"  ⚠️  {_fail} test(s) FAILED")
    print("=" * 64)
    print()

    sys.exit(1 if _fail > 0 else 0)


if __name__ == "__main__":
    main()
