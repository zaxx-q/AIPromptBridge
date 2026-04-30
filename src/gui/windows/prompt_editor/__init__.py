#!/usr/bin/env python3
"""
Prompt Editor Package for AIPromptBridge.

Modular prompt editor window split into:
- data.py: JSON I/O utilities and constants
- dialogs.py: ThemedInputDialog, TestResultDialog, PresetManagerDialog
- editor.py: Core PromptEditorWindow composing all tab mixins
- tab_actions.py: Actions tab (ActionsTabMixin)
- tab_settings.py: Settings tab (SettingsTabMixin)
- tab_modifiers.py: Modifiers tab (ModifiersTabMixin)
- tab_groups.py: Groups tab (GroupsTabMixin)
- tab_playground.py: Playground tab (PlaygroundTabMixin)
- tab_tts_playground.py: TTS Playground (TTSPlaygroundMixin)

Public API:
- PromptEditorWindow: Main editor window class
- AttachedPromptEditorWindow: Editor as child of GUICoordinator root
- create_attached_prompt_editor_window: Factory for attached editor
- show_prompt_editor: Thread-safe shortcut to show editor
- PresetManagerDialog: Standalone model preset manager (usable outside editor)
"""

from .editor import (
    PromptEditorWindow,
    AttachedPromptEditorWindow,
    create_attached_prompt_editor_window,
    show_prompt_editor,
)

from .dialogs import PresetManagerDialog

__all__ = [
    'PromptEditorWindow',
    'AttachedPromptEditorWindow',
    'create_attached_prompt_editor_window',
    'show_prompt_editor',
    'PresetManagerDialog',
]
