#!/usr/bin/env python3
"""Convert prompts.json + tools_config.json into a tree of clean markdown files.

Layout
------
out/
  README.md                  index of everything, grouped as in the app's popup menus
  global.md                  chat-window instruction + modifiers
  text-edit-tool/            one .md per prompt  (+ _settings.md)
  snip-tool/                 one .md per prompt  (+ _settings.md)
  audio-tool/                one .md per prompt  (+ _settings.md)
  tts-tool/                  director.md
  file-processor/            one .md per prompt  (+ _settings.md)

Each prompt file = YAML frontmatter (metadata) + one section per text field.
Prompt text is placed in fenced code blocks so XML tags / markdown inside the
prompts are preserved exactly instead of being interpreted by a renderer.

Usage
-----
  python extract_prompts.py prompts.json tools_config.json -o out/
"""

import argparse
import json
import re
import shutil
from pathlib import Path

# Fields that are rendered as a body section (when non-empty) instead of frontmatter.
SECTION_TITLES = {"system_prompt": "System Prompt", "task": "Task", "prompt": "Prompt"}
SHORT_STRING_MAX = 80  # settings strings up to this length go in a table, not a fence

# Friendly names for the top-level tool keys in prompts.json
TOOL_DIRS = {
    "text_edit_tool": ("text-edit-tool", "Text Edit Tool"),
    "snip_tool": ("snip-tool", "Snip Tool (images)"),
    "audio_tool": ("audio-tool", "Audio Tool"),
}


# ───────────────────────── helpers ─────────────────────────
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "item"


def unique_slug(name: str, used: set) -> str:
    base = slug = slugify(name)
    i = 2
    while slug in used:
        slug, i = f"{base}-{i}", i + 1
    used.add(slug)
    return slug


def fence(text: str, lang: str = "text") -> str:
    """Fenced block whose fence is longer than any backtick run inside the text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}{lang}\n{text}\n{f}"


def yaml_value(v) -> str:
    # JSON is valid YAML, so json.dumps gives safe quoting for every type.
    return json.dumps(v, ensure_ascii=False)


def frontmatter(d: dict) -> str:
    lines = ["---"] + [f"{k}: {yaml_value(v)}" for k, v in d.items()] + ["---"]
    return "\n".join(lines)


def cell(v) -> str:
    return "`" + yaml_value(v).replace("|", "\\|") + "`"


def title_case(key: str) -> str:
    return key.strip("_").replace("_", " ").title()


def blurb(text, limit: int = 110) -> str:
    """First sentence of a string, trimmed for use in the index."""
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s", text.strip().splitlines()[0], maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")


# ───────────────────────── renderers ─────────────────────────
def split_entry(entry: dict):
    """Split a prompt dict into (frontmatter fields, ordered body sections)."""
    meta, sections = {}, []
    for k, v in entry.items():
        is_text = isinstance(v, str) and v != "" and (k in SECTION_TITLES or "\n" in v or len(v) > 200)
        if is_text:
            sections.append((SECTION_TITLES.get(k, title_case(k)), k, v))
        else:
            meta[k] = v
    return meta, sections


def render_prompt_file(name: str, entry: dict, group: str | None = None) -> str:
    meta, sections = split_entry(entry)
    fm = {"name": name}
    if group:
        fm["group"] = group
    fm.update(meta)
    icon = entry.get("icon", "")
    title = f"{icon} {name}".strip() if isinstance(icon, str) else name
    parts = [frontmatter(fm), "", f"# {title}"]
    desc = entry.get("description")
    if isinstance(desc, str) and desc:
        parts += ["", f"> {desc}"]
    for heading, _key, text in sections:
        parts += ["", f"## {heading}", "", fence(text)]
    return "\n".join(parts)


def render_value(key: str, v, level: int = 2) -> str:
    """Render one settings value as a section (used for non-table values)."""
    h = "#" * level
    if isinstance(v, str):
        return f"{h} `{key}`\n\n{fence(v)}"
    if key == "popup_groups" and isinstance(v, list):
        out = [f"{h} `{key}`"]
        for g in v:
            state = "" if g.get("enabled", True) else " *(disabled)*"
            out.append(f"\n**{g['name']}**{state}\n")
            out += [f"- {i}" for i in g["items"]]
        return "\n".join(out)
    return f"{h} `{key}`\n\n{fence(json.dumps(v, indent=2, ensure_ascii=False), 'json')}"


def render_settings(title: str, d: dict) -> str:
    table = [
        (k, v)
        for k, v in d.items()
        if not isinstance(v, (dict, list)) and not (isinstance(v, str) and len(v) > SHORT_STRING_MAX)
    ]
    rest = [(k, v) for k, v in d.items() if (k, v) not in table]
    parts = [f"# {title}"]
    if table:
        parts += ["", "| Setting | Value |", "|---|---|"]
        parts += [f"| `{k}` | {cell(v)} |" for k, v in table]
    for k, v in rest:
        parts += ["", render_value(k, v)]
    return "\n".join(parts)


def render_modifiers(mods: list) -> str:
    parts = ["## Modifiers", "", "Snippets appended to a prompt when the user toggles a modifier."]
    for m in mods:
        icon, label = m.get("icon", ""), m.get("label", m.get("key", ""))
        parts += ["", f"### {icon} {label}".replace("  ", " ")]
        for k, v in m.items():
            if k != "injection":
                parts.append(f"- **{k}**: {cell(v)}")
        if m.get("injection"):
            parts += ["", fence(m["injection"], "xml")]
    return "\n".join(parts)


# ───────────────────────── main build ─────────────────────────
def build(prompts: dict, tools: dict, out: Path):
    index = [
        "# Prompt Library",
        "",
        f"_Generated from `prompts.json` (v{prompts['_global_settings'].get('version', '?')}"
        f": {prompts['_global_settings'].get('description', '')}) and `tools_config.json`._",
        "",
    ]
    written = {}  # relpath -> (kind, name, entry) for verification

    # ---- global.md
    g = prompts["_global_settings"]
    gl = ["# Global Settings", ""]
    gl += [f"- **version**: {cell(g.get('version'))}", f"- **description**: {g.get('description', '')}", ""]
    gl += ["## Chat window system instruction", "", fence(g["chat_window_system_instruction"]), ""]
    gl += [render_modifiers(g.get("modifiers", []))]
    write(out / "global.md", "\n".join(gl))
    index += ["## Global", "", "- [Global settings & modifiers](global.md)", ""]

    # ---- per-tool prompt folders
    for key, (dirname, label) in TOOL_DIRS.items():
        tool = prompts[key]
        settings = tool.get("_settings", {})
        groups = settings.get("popup_groups") or settings.get("groups") or []
        group_of = {item: grp["name"] for grp in groups for item in grp["items"]}
        used, slugs = set(), {}
        for name, entry in tool.items():
            if name == "_settings":
                continue
            slugs[name] = unique_slug(name, used)
            rel = f"{dirname}/{slugs[name]}.md"
            write(out / rel, render_prompt_file(name, entry, group_of.get(name)))
            written[rel] = (name, entry, group_of.get(name))
        write(out / dirname / "_settings.md", render_settings(f"{label} — Settings", settings))

        # index section, ordered by popup groups
        index += [f"## {label}", "", f"[Settings]({dirname}/_settings.md)", ""]
        placed = set()

        def line(n, _tool=tool, _dirname=dirname, _slugs=slugs):
            e = _tool[n]
            first = blurb(e.get("task"))
            return f"- {e.get('icon', '')} [{n}]({_dirname}/{_slugs[n]}.md)" + (f" — {first}" if first else "")

        for grp in groups:
            present = [i for i in grp["items"] if i in tool]
            missing = [i for i in grp["items"] if i not in tool]
            index += [f"### {grp['name']}", ""] + [line(i) for i in present]
            index += [f"- ~~{i}~~ _(listed in popup_groups but not defined)_" for i in missing] + [""]
            placed.update(present)
        other = [n for n in slugs if n not in placed]
        if other:
            index += ["### Other", ""] + [line(n) for n in other] + [""]

    # ---- tts tool
    tts = prompts.get("tts_tool", {}).get("_settings", {})
    if tts:
        meta = {k: v for k, v in tts.items() if k not in ("director_system_prompt", "director_task_template")}
        entry = {
            "system_prompt": tts.get("director_system_prompt", ""),
            "task": tts.get("director_task_template", ""),
            **meta,
        }
        write(out / "tts-tool/director.md", render_prompt_file("TTS Director", entry))
        written["tts-tool/director.md"] = ("TTS Director", entry, None)
        index += ["## TTS Tool", "", "- [TTS Director](tts-tool/director.md)", ""]

    # ---- file processor (tools_config.json)
    fp = tools["file_processor"]
    used, slugs = set(), {}
    for name, entry in fp["prompts"].items():
        slugs[name] = unique_slug(name, used)
        rel = f"file-processor/{slugs[name]}.md"
        write(out / rel, render_prompt_file(name, entry))
        written[rel] = (name, entry, None)
    cfg = dict(tools.get("_settings", {}))
    body = [render_settings("File Processor — Settings", cfg)]
    for k in ("output_modes", "file_type_mappings"):
        if k in fp:
            body += ["", render_value(k, fp[k])]
    write(out / "file-processor/_settings.md", "\n".join(body))
    index += ["## File Processor", "", "[Settings & file-type mappings](file-processor/_settings.md)", ""]
    for name, entry in fp["prompts"].items():
        d = blurb(entry.get("description", ""))
        index.append(f"- {entry.get('icon', '')} [{name}](file-processor/{slugs[name]}.md)" + (f" — {d}" if d else ""))
    index.append("")

    write(out / "README.md", "\n".join(index))
    return written


# ───────────────────────── verification ─────────────────────────
def parse_prompt_file(text: str):
    _, fm, body = text.split("---\n", 2)
    meta = {}
    for ln in fm.strip().splitlines():
        k, v = ln.split(": ", 1)
        meta[k] = json.loads(v)
    secs = {}
    pat = re.compile(r"^## ([^\n]+)\n\n(`{3,})text\n(.*?)\n\2$", re.S | re.M)
    for m in pat.finditer(body):
        secs[m.group(1)] = m.group(3)
    return meta, secs


def string_leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from string_leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from string_leaves(v)
    elif isinstance(o, str) and o:
        yield o


def verify(prompts, tools, out: Path, written: dict) -> bool:
    ok = True
    # 1) exact round-trip of every per-prompt file
    for rel, (_name, entry, _grp) in written.items():
        meta, secs = parse_prompt_file((out / rel).read_text(encoding="utf-8"))
        rebuilt = dict(meta)
        rebuilt.pop("name", None)
        rebuilt.pop("group", None)
        for heading, key, _text in split_entry(entry)[1]:
            rebuilt[key] = secs.get(heading)
        if {k: rebuilt.get(k) for k in entry} != entry:
            print(f"  MISMATCH: {rel}")
            ok = False
    # 2) every non-empty string in both JSON files appears somewhere in the output
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    missing = 0
    for src in (prompts, tools):
        for s in string_leaves(src):
            if s not in corpus and json.dumps(s, ensure_ascii=False)[1:-1].replace("|", "\\|") not in corpus:
                missing += 1
                print(f"  NOT FOUND: {s[:60]!r}")
    ok &= missing == 0
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompts_json")
    ap.add_argument("tools_config_json")
    ap.add_argument("-o", "--out", default="prompts_md")
    ap.add_argument("--no-clean", action="store_true", help="don't wipe the output dir first")
    a = ap.parse_args()

    prompts = json.loads(Path(a.prompts_json).read_text(encoding="utf-8"))
    tools = json.loads(Path(a.tools_config_json).read_text(encoding="utf-8"))
    out = Path(a.out)
    if out.exists() and not a.no_clean:
        shutil.rmtree(out)
    written = build(prompts, tools, out)
    n_files = sum(1 for _ in out.rglob("*.md"))
    print(f"Wrote {n_files} markdown files ({len(written)} prompts) to {out}/")
    print("Verification:", "PASSED" if verify(prompts, tools, out, written) else "FAILED")


if __name__ == "__main__":
    main()
