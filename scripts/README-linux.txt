AIPromptBridge — Linux package
==============================

Layout
------
  AIPromptBridge              Outer launcher (run this)
  bin/AIPromptBridge_Internal Nuitka standalone app
  bin/…                       Bundled libraries and assets
  README-linux.txt            This file

Quick start
-----------
  tar -xzf AIPromptBridge-*-linux-x86_64.tar.gz
  cd AIPromptBridge-*-linux-x86_64   # or the extracted folder name
  ./AIPromptBridge --show-console

  # IPC triggers (requires a running instance), e.g. from niri binds:
  ./AIPromptBridge --trigger textedit
  ./AIPromptBridge --trigger snip
  ./AIPromptBridge --trigger audio

Config (config.ini, keys.json, prompts.json, sessions) is CWD-relative:
keep the deploy folder as your working directory, or launch via the
absolute path to ./AIPromptBridge from that folder.

Runtime system packages (not bundled)
-------------------------------------
  wl-clipboard   clipboard / primary selection
  wlrctl         type / paste into apps (wlroots)
  grim, slurp    screen snip
  pactl          Pulse/PipeWire monitor discovery (system audio)
  ffmpeg         pulse capture for system audio (+ optional sounds)
  libportaudio2  mic capture via PyAudio (if not fully bundled)
  StatusNotifier host (e.g. waybar / dms) for tray

Build baseline: glibc from Ubuntu 24.04 (x86_64). Older distros may
need a newer glibc or a source install instead.

Self-update
-----------
  Compiled Linux builds currently notify when a new release exists;
  download and extract the new tarball manually. Windows compiled
  builds support in-place self-update.

More detail: docs/LINUX.md in the source repository.
