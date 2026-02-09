import sys
import os
import shutil
from cx_Freeze import setup, Executable

# Minimalistic build options for the launcher
# We aggressively exclude everything that is not strictly needed for os, sys, subprocess, and simple logic.
build_exe_options = {
    "packages": [],
    "excludes": [
        "tkinter", "unittest", "email", "http", "xml", "pydoc", "pdb",
        "distutils", "setuptools", "multiprocessing", "logging",
        "html", "ctypes.test", "concurrent", "asyncio", "json", "sqlite3",
        "ssl", "socket", "bz2", "lzma", "decimal",
        "hashlib", "hmac", "secrets", "random", "bisect", "shutil",
        "tempfile", "weakref", "base64", "calendar", "datetime",
        "urllib", "zipfile", "tarfile", "_hashlib", "_ssl", "_decimal",
        # Aggressive excludes for minimal launcher
        "importlib.metadata", "importlib.resources",
        "ctypes", "ctypes.macholib", "ctypes.wintypes",
        "sysconfig", "pydoc_data", "socket",
        "zoneinfo", "typing", "difflib", "doctest", "optparse",
        "pickle", "pprint", "statistics", "textwrap", "uu", "uuid", "plistlib",
        "platform", "inspect", "dis", "opcode", "pathlib", "fnmatch", "pkg_resources",
        # Exclude specific encodings (keep utf_8, ascii, mbcs, latin_1, and Thai cp874/tis_620)
        "encodings.idna", "encodings.punycode", "encodings.hex_codec",
        "encodings.hp_roman8", "encodings.mac_roman", "encodings.mac_turkish",
        "encodings.mac_iceland", "encodings.mac_greek", "encodings.mac_farsi",
        "encodings.mac_cyrillic", "encodings.mac_croatian", "encodings.mac_arabic",
        "encodings.mac_latin2", "encodings.mac_romanian",
        "encodings.cp037", "encodings.cp273", "encodings.cp424", "encodings.cp500",
        "encodings.cp720", "encodings.cp737", "encodings.cp775", "encodings.cp850",
        "encodings.cp852", "encodings.cp855", "encodings.cp856", "encodings.cp857",
        "encodings.cp858", "encodings.cp860", "encodings.cp861", "encodings.cp862",
        "encodings.cp863", "encodings.cp864", "encodings.cp865", "encodings.cp866",
        "encodings.cp869", "encodings.cp1006", "encodings.cp1026", "encodings.cp1125",
        "encodings.cp1250", "encodings.cp1251", "encodings.cp1253", "encodings.cp1254",
        "encodings.cp1255", "encodings.cp1256", "encodings.cp1257", "encodings.cp1258",
        "encodings.euc_jis_2004", "encodings.euc_jisx0213", "encodings.euc_jp",
        "encodings.euc_kr", "encodings.gb2312", "encodings.gb18030", "encodings.gbk",
        "encodings.iso2022_jp", "encodings.iso2022_jp_1", "encodings.iso2022_jp_2",
        "encodings.iso2022_jp_3", "encodings.iso2022_jp_2004", "encodings.iso2022_jp_ext",
        "encodings.iso2022_kr", "encodings.johab", "encodings.shift_jis",
        "encodings.shift_jis_2004", "encodings.shift_jisx0213",
        "encodings.koi8_r", "encodings.koi8_t", "encodings.koi8_u", "encodings.kz1048",
        "encodings.hz", "encodings.palmos", "encodings.ptcp154", "encodings.undefined",
        "encodings.rot_13", "encodings.quopri_codec", "encodings.uu_codec", "encodings.zlib_codec"
    ],
    # cx_Freeze might still pull in some DLLs (like libcrypto) if it thinks they are needed by the runtime.
    # We can try to exclude them explicitly in bin_excludes if they persist.
    "bin_excludes": [
        "libcrypto-3.dll", "libssl-3.dll", "unicodedata.pyd", "_hashlib.pyd", "_ssl.pyd",
        "_ctypes.pyd", "libffi-8.dll", "_socket.pyd", "select.pyd"
    ],
    "zip_exclude_packages": [
        "email", "importlib", "ctypes", "typing", "distutils", "setuptools",
        "multiprocessing", "logging", "unittest", "pydoc_data", "sysconfig", "pkg_resources"
    ],
    "include_files": [],
    "optimize": 2,
    "build_exe": "build_launchers_cx"
}

# Define the executables
executables = [
    # Console Launcher (AIPromptBridge.exe)
    Executable(
        "src/launchers/launcher_console.py",
        base="console",
        target_name="AIPromptBridge.exe",
        icon="icon.ico",
        manifest="src/launchers/app.manifest"
    ),
    # GUI/No-Console Launcher (AIPromptBridge-NoConsole.exe)
    Executable(
        "src/launchers/launcher_gui.py",
        base="gui", # No console window
        target_name="AIPromptBridge-NoConsole.exe",
        icon="icon.ico",
        manifest="src/launchers/app.manifest"
    )
]

setup(
    name="AIPromptBridge Launcher",
    version="1.0.0",
    description="Launcher for AIPromptBridge",
    options={"build_exe": build_exe_options},
    executables=executables
)

# --- Post-Build Cleanup (The Nuclear Option) ---
# cx_Freeze insists on including 'email' despite all excludes.
# We verified it's safe to delete at runtime, so we do it manually here.
if "build" in sys.argv:
    print("\n[Post-Build] Performing cleanup...")
    build_dir = "build_launchers_cx"
    email_dir = os.path.join(build_dir, "lib", "email")
    
    if os.path.exists(email_dir):
        print(f"[Post-Build] Removing persistent '{email_dir}'...")
        try:
            shutil.rmtree(email_dir)
            print("[Post-Build] Cleanup successful! 'email' package removed.")
        except Exception as e:
            print(f"[Post-Build] Failed to remove 'email' package: {e}")
    else:
        print("[Post-Build] 'email' package not found (already clean?).")
