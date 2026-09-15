AIPromptBridge — Linux package
==============================

Layout
------
  AIPromptBridge              Outer launcher (run this)
  aipb_trigger.py             Fast stdlib IPC client (--trigger path)
  bin/AIPromptBridge_Internal Nuitka standalone app
  bin/…                       Bundled libraries and assets
  README-linux.txt            This file

Quick start
-----------
  tar -xzf AIPromptBridge-*-linux-x86_64.tar.gz
  cd AIPromptBridge-*-linux-x86_64   # or the extracted folder name
  ./AIPromptBridge --show-console
  # To run directly in this terminal instead of tmux:
  ./AIPromptBridge --no-tmux --show-console

  # IPC triggers (requires a running instance), e.g. from niri binds.
  # --trigger uses aipb_trigger.py + system python3 (tens of ms), NOT the
  # full Nuitka binary:
  ./AIPromptBridge --trigger textedit
  # Process intentionally copied clipboard text; does not synthesize Ctrl+C.
  ./AIPromptBridge --trigger textedit-clipboard
  ./AIPromptBridge --trigger snip
  ./AIPromptBridge --trigger audio

Optional PATH install (symlink the outer launcher only — keep bin/ next to it):
  mkdir -p ~/.local/AIPromptBridge
  # move/extract the full package into ~/.local/AIPromptBridge/
  ln -sf ~/.local/AIPromptBridge/AIPromptBridge ~/.local/bin/AIPromptBridge
  # Then: AIPromptBridge --show-console

Config (config.ini, keys.json, prompts.json, sessions) lives in the deploy
root (the folder that contains AIPromptBridge + bin/), not next to a PATH
symlink. The launcher always chdirs there.

Runtime system packages (not bundled)
-------------------------------------
  wl-clipboard   clipboard / primary selection
  wtype / wlrctl type / paste into apps (wtype recommended for smooth typing)
  grim, slurp    screen snip
  pactl          Pulse/PipeWire monitor discovery (system audio)
  ffmpeg         pulse capture for system audio (+ optional sounds)
  libportaudio2  mic capture via PyAudio (if not fully bundled)
  StatusNotifier host (e.g. waybar / dms) for tray
  tmux           persistent console session and tray terminal attachment (optional)

Build baseline: glibc from Ubuntu 24.04 (x86_64). Older distros may
need a newer glibc or a source install instead.

Interactive console (tmux)
--------------------------
  When tmux is installed, launches run in a named session "aipromptbridge".
  Pass --no-tmux to bypass it and keep the app's logs in the launching terminal.
  You can attach to the running console at any time:
    - via tray menu: "Open Terminal (tmux)"
    - via terminal:  tmux attach-session -t aipromptbridge

Self-update
-----------
  Compiled Linux builds support in-place self-update: download, extract,
  swap bin/ and root files, then relaunch. Source installs are
  notification-only.

More detail: docs/LINUX.md in the source repository.
