"""Tests for the Prompt Editor's Groups tab action picker (choose a group's actions from a list)."""

from __future__ import annotations

import copy
import tkinter as tk

import pytest

from src.gui.windows.prompt_editor.data import get_group_action_choices, group_action_status

# =============================================================================
# Pure logic (no GUI)
# =============================================================================


def _tool_data():
    return {
        "_settings": {"popup_groups": []},
        "Proofread": {"icon": "✏️"},
        "Explain": {"icon": "💡"},
        "Secret": {"icon": "🤫", "_hidden": True},
        "NoIcon": {},
        "Custom": {"icon": "⭐"},
    }


def test_status_ok_hidden_missing():
    data = _tool_data()
    assert group_action_status("snip_tool", data, "Proofread") == "ok"
    assert group_action_status("snip_tool", data, "Secret") == "hidden"
    assert group_action_status("snip_tool", data, "Deleted Long Ago") == "missing"


def test_status_never_treats_internal_keys_as_actions():
    data = _tool_data()
    assert group_action_status("text_edit_tool", data, "_settings") == "missing"
    assert group_action_status("text_edit_tool", data, "_Ask") == "missing"
    # Malformed JSON entries must not raise
    assert group_action_status("text_edit_tool", data, None) == "missing"
    assert group_action_status("text_edit_tool", {"Bad": "not a dict"}, "Bad") == "missing"


def test_custom_is_reserved_only_for_text_edit():
    """The Text Edit popup adds its own "Custom" entry; the other popups have no such rule."""
    data = _tool_data()
    assert group_action_status("text_edit_tool", data, "Custom") == "missing"
    assert group_action_status("snip_tool", data, "Custom") == "ok"
    assert group_action_status("audio_tool", data, "Custom") == "ok"


def test_choices_keep_actions_tab_order_and_skip_unusable():
    data = _tool_data()
    assert get_group_action_choices("text_edit_tool", data) == [("Proofread", "✏️"), ("Explain", "💡"), ("NoIcon", "")]
    # Snip may use an action called "Custom"
    assert ("Custom", "⭐") in get_group_action_choices("snip_tool", data)


def test_choices_match_what_the_popups_would_render():
    """Everything offered by the picker must survive the popups' own filtering."""
    from src.gui.prompts import PromptsConfig

    defaults = PromptsConfig()._get_defaults()
    for tool in ("text_edit_tool", "snip_tool", "audio_tool"):
        tool_data = defaults[tool]
        names = [n for n, _ in get_group_action_choices(tool, tool_data)]
        assert names, f"{tool} should offer actions"
        assert all(not n.startswith("_") and not tool_data[n].get("_hidden", False) for n in names)


def test_every_default_group_item_is_a_known_action():
    """Shipped groups must not reference actions that don't exist (they'd show as 'not found')."""
    from src.gui.prompts import PromptsConfig

    defaults = PromptsConfig()._get_defaults()
    for tool in ("text_edit_tool", "snip_tool", "audio_tool"):
        tool_data = defaults[tool]
        for group in tool_data["_settings"]["popup_groups"]:
            for item in group["items"]:
                assert group_action_status(tool, tool_data, item) == "ok", f"{tool}/{group['name']}: {item}"


# =============================================================================
# GUI behaviour (headless; skipped without a display)
# =============================================================================


@pytest.fixture
def editor(monkeypatch):
    """A real PromptEditorWindow on a private copy of the default prompts, with the Groups tab open."""
    from src.gui.platform import HAVE_CTK, ctk
    from src.gui.prompts import PromptsConfig
    from src.gui.windows.prompt_editor import editor as editor_module

    try:
        master = ctk.CTk() if HAVE_CTK else tk.Tk()
        master.withdraw()
    except tk.TclError:
        pytest.skip("Tkinter TclError (no display available)")
        return

    # Private deep copy: load_options() normally hands out the live singleton config
    monkeypatch.setattr(editor_module, "load_options", lambda: copy.deepcopy(PromptsConfig()._get_defaults()))

    ed = editor_module.PromptEditorWindow(master=master)
    try:
        ed.show()
        if ed.use_ctk:
            ed.tabview.set("📁 Groups")
            ed._on_tab_changed()
        else:
            ed.tabview.select(1)
        ed.root.update()
        yield ed
    finally:
        from src.gui.core import unregister_window

        ed._destroyed = True
        unregister_window(ed.window_tag)
        try:
            ed.root.destroy()
            master.destroy()
        except tk.TclError:
            pass


def _available(ed):
    return [i for i in ed.group_widgets["available_list"].items if i != "__empty__"]


def _popup_groups(ed, tool="text_edit_tool"):
    return ed.options_data[tool]["_settings"]["popup_groups"]


def test_pick_reorder_remove_and_save(editor):
    ed = editor
    ed.group_listbox.select("1")  # "Understanding"
    original = list(_popup_groups(ed)[1]["items"])

    assert ed._group_items == original
    assert "Proofread" in _available(ed)
    assert not set(original) & set(_available(ed)), "actions already in the group are not offered again"

    # Click-to-add appends; the stored group stays untouched until Save Group
    ed._on_group_action_pick("Proofread")
    ed._on_group_action_pick("Refine")
    assert ed._group_items == [*original, "Proofread", "Refine"]
    assert "Proofread" not in _available(ed)
    assert _popup_groups(ed)[1]["items"] == original

    # Reorder the selected row, then remove another
    ed.group_widgets["items_list"].select(str(len(ed._group_items) - 1))
    ed._move_group_item(-1)
    assert ed._group_items[-2:] == ["Refine", "Proofread"]
    ed._remove_group_item()  # removes the selected (moved) row
    assert "Refine" not in ed._group_items
    assert "Refine" in _available(ed), "a removed action becomes available again"

    ed._save_current_group()
    assert _popup_groups(ed)[1]["items"] == [*original, "Proofread"]


def test_filter_is_case_insensitive_and_excludes_added(editor):
    ed = editor
    ed.group_listbox.select("1")
    entry = ed.group_widgets["filter_entry"]

    entry.insert(0, "PRO")
    ed._apply_group_filter()
    names = _available(ed)
    assert "Proofread" in names and all("pro" in n.lower() for n in names)

    entry.delete(0, "end")
    entry.insert(0, "trans")  # both "Translate to ..." actions are already in this group
    ed._apply_group_filter()
    assert _available(ed) == []
    assert ed.group_widgets["available_list"].items == ["__empty__"]


def test_picker_is_inert_until_a_group_is_selected(editor):
    ed = editor
    assert ed._group_edit_index is None
    assert ed.group_widgets["available_list"].items == ["__empty__"]
    ed._on_group_action_pick("Proofread")
    ed._on_group_action_pick("__empty__")
    assert ed._group_items == []


def test_hidden_and_missing_items_are_kept_flagged_and_removable(editor):
    ed = editor
    data = ed.options_data["text_edit_tool"]
    data["Digest"]["_hidden"] = True
    _popup_groups(ed)[1]["items"].append("Ghost Action")

    ed.group_listbox.select("1")
    assert "Digest" in ed._group_items and "Ghost Action" in ed._group_items, "nothing is silently dropped"
    assert "Digest" not in _available(ed), "hidden actions are not offered"

    labels = [b.cget("text").strip() for b in ed.group_widgets["items_list"].buttons.values()]
    assert any(t.startswith("⊘") and "Digest" in t for t in labels)
    assert any(t.startswith("⚠") and "Ghost Action" in t for t in labels)

    ed.group_widgets["items_list"].select(str(ed._group_items.index("Ghost Action")))
    ed._remove_group_item()
    assert "Ghost Action" not in ed._group_items


def test_new_group_opens_in_the_picker_and_deleting_the_last_clears_it(editor, monkeypatch):
    from src.gui.windows.prompt_editor import tab_groups

    ed = editor
    count = len(_popup_groups(ed))
    monkeypatch.setattr(tab_groups, "ask_themed_string", lambda *a, **k: "Fresh Group")
    ed._add_group()

    assert ed._group_edit_index == count, "the new group is selected so actions can be picked right away"
    ed._on_group_action_pick("Proofread")
    ed._save_current_group()
    assert _popup_groups(ed)[count] == {"name": "Fresh Group", "enabled": True, "items": ["Proofread"]}

    monkeypatch.setattr(tab_groups.messagebox, "askyesno", lambda *a, **k: True)
    ed._delete_group()
    assert len(_popup_groups(ed)) == count
    assert ed._group_edit_index is None and ed._group_items == [], "no deleted group left open in the editor"


def test_picker_follows_tool_switches(editor):
    ed = editor
    if not ed.use_ctk:
        pytest.skip("the tool switcher only exists with CustomTkinter")

    ed.group_listbox.select("0")
    ed.group_tool_switcher.set("Snip Tool")
    ed._on_group_tool_switch("Snip Tool")

    assert ed.group_listbox.get_selected() is None, "no group stays highlighted over a blank editor"
    assert ed._group_edit_index is None

    ed.group_listbox.select("0")
    snip_actions = set(ed.options_data["snip_tool"]) - {"_settings"}
    assert set(_available(ed)) | set(ed._group_items) <= snip_actions
    assert "Proofread" not in _available(ed), "Text Edit actions are not offered for Snip groups"


def test_actions_changed_elsewhere_show_up_when_returning_to_groups(editor):
    ed = editor
    ed.group_listbox.select("0")
    ed.options_data["text_edit_tool"]["Brand New"] = {"icon": "🆕", "system_prompt": "", "task": ""}
    assert "Brand New" not in _available(ed), "picker is a snapshot until the tab is shown again"

    ed._on_groups_tab_shown()
    assert "Brand New" in _available(ed)
