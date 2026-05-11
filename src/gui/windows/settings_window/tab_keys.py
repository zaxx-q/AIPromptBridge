#!/usr/bin/env python3
"""
API Keys tab mixin for Settings Window — Pool-based key management.

Layout:
    ┌────────────────┬─────────────────────────────────┐
    │  Pool List     │  Keys for selected pool         │
    │  (left)        │  (right)                        │
    │                │                                 │
    │  [+ Add Pool]  │  key entry + add/remove/reorder │
    │  [- Remove]    │                                 │
    │  [✎ Rename]    │                                 │
    └────────────────┴─────────────────────────────────┘

Provider → Pool assignment is in the Provider tab (tab_provider.py).
"""

import tkinter as tk
from tkinter import simpledialog

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors, get_ctk_entry_colors
from ...custom_widgets import ScrollableButtonList, create_emoji_button, create_section_header


class KeysTabMixin:
    """Mixin providing the API Keys tab for SettingsWindow."""

    def _create_keys_tab(self, frame):
        """Create the API Keys settings tab with pool-based layout."""
        from src.key_store import KeyStore
        self._key_store = KeyStore.get_instance()

        container = ctk.CTkFrame(frame, fg_color="transparent") if self.use_ctk else tk.Frame(frame, bg=self.colors.bg)
        container.pack(fill="both", expand=True, padx=15, pady=15)

        # --- Top area: Pool list (left) + Key list (right) ---
        top_frame = ctk.CTkFrame(container, fg_color="transparent") if self.use_ctk else tk.Frame(container, bg=self.colors.bg)
        top_frame.pack(fill="both", expand=True)
        top_frame.columnconfigure(1, weight=1)
        top_frame.rowconfigure(0, weight=1)

        # === Left panel: Pool list ===
        left_frame = ctk.CTkFrame(top_frame, fg_color="transparent") if self.use_ctk else tk.Frame(top_frame, bg=self.colors.bg)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        create_section_header(left_frame, "🗂️ Key Pools", self.colors)

        if self.use_ctk:
            pool_list = ScrollableButtonList(
                left_frame, self.colors, command=self._on_pool_selected,
                corner_radius=8, fg_color=self.colors.input_bg, width=180
            )
        else:
            pool_list = ScrollableButtonList(
                left_frame, self.colors, command=self._on_pool_selected,
                bg=self.colors.input_bg, width=180
            )
        pool_list.pack(fill="both", expand=True, pady=(6, 0))
        self.widgets["keys_pool_list"] = pool_list

        # Pool action buttons
        pool_btn_frame = ctk.CTkFrame(left_frame, fg_color="transparent") if self.use_ctk else tk.Frame(left_frame, bg=self.colors.bg)
        pool_btn_frame.pack(fill="x", pady=(8, 0))

        create_emoji_button(pool_btn_frame, "+ Pool", "", self.colors, "success", 75, 32, self._add_pool).pack(side="left", padx=2)
        create_emoji_button(pool_btn_frame, "✎", "", self.colors, "secondary", 35, 32, self._rename_pool).pack(side="left", padx=2)
        create_emoji_button(pool_btn_frame, "✕", "", self.colors, "danger", 35, 32, self._remove_pool).pack(side="left", padx=2)

        # === Right panel: Keys for selected pool ===
        right_frame = ctk.CTkFrame(top_frame, fg_color="transparent") if self.use_ctk else tk.Frame(top_frame, bg=self.colors.bg)
        right_frame.grid(row=0, column=1, sticky="nsew")

        self._keys_header_var = tk.StringVar(master=self.root, value="🔑 Keys")
        if self.use_ctk:
            self._keys_header_label = ctk.CTkLabel(
                right_frame, textvariable=self._keys_header_var,
                font=get_ctk_font(14, "bold"),
                **get_ctk_label_colors(self.colors)
            )
        else:
            self._keys_header_label = tk.Label(
                right_frame, textvariable=self._keys_header_var,
                font=("Segoe UI", 11, "bold"),
                bg=self.colors.bg, fg=self.colors.fg
            )
        self._keys_header_label.pack(anchor="w")

        if self.use_ctk:
            key_list = ScrollableButtonList(
                right_frame, self.colors, command=None,
                corner_radius=8, fg_color=self.colors.input_bg
            )
        else:
            key_list = ScrollableButtonList(
                right_frame, self.colors, command=None,
                bg=self.colors.input_bg
            )
        key_list.pack(fill="both", expand=True, pady=(6, 0))
        self.widgets["keys_key_list"] = key_list

        # Key input row
        input_frame = ctk.CTkFrame(right_frame, fg_color="transparent") if self.use_ctk else tk.Frame(right_frame, bg=self.colors.bg)
        input_frame.pack(fill="x", pady=(10, 0))

        if self.use_ctk:
            ctk.CTkLabel(
                input_frame, text="Key:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors)
            ).pack(side="left", padx=(0, 4))

            key_var = tk.StringVar(master=self.root)
            key_entry = ctk.CTkEntry(
                input_frame, textvariable=key_var,
                font=get_ctk_font(12), width=260, height=36,
                placeholder_text="Paste API key…",
                **get_ctk_entry_colors(self.colors)
            )
            key_entry.pack(side="left", padx=(0, 10))

            ctk.CTkLabel(
                input_frame, text="Name:",
                font=get_ctk_font(12),
                **get_ctk_label_colors(self.colors)
            ).pack(side="left", padx=(0, 4))

            name_var = tk.StringVar(master=self.root)
            name_entry = ctk.CTkEntry(
                input_frame, textvariable=name_var,
                font=get_ctk_font(12), width=130, height=36,
                placeholder_text="Optional…",
                **get_ctk_entry_colors(self.colors)
            )
            name_entry.pack(side="left", padx=(0, 8))
        else:
            key_var = tk.StringVar(master=self.root)
            key_entry = tk.Entry(
                input_frame, textvariable=key_var,
                font=("Consolas", 10), width=32,
                bg=self.colors.input_bg, fg=self.colors.fg
            )
            key_entry.pack(side="left", padx=(0, 6))

            name_var = tk.StringVar(master=self.root)
            name_entry = tk.Entry(
                input_frame, textvariable=name_var,
                font=("Segoe UI", 10), width=14,
                bg=self.colors.input_bg, fg=self.colors.fg
            )
            name_entry.pack(side="left", padx=(0, 6))

        self.widgets["keys_key_var"] = key_var
        self.widgets["keys_name_var"] = name_var

        # Key action buttons
        key_btn_frame = ctk.CTkFrame(right_frame, fg_color="transparent") if self.use_ctk else tk.Frame(right_frame, bg=self.colors.bg)
        key_btn_frame.pack(fill="x", pady=(8, 0))

        create_emoji_button(key_btn_frame, "Add", "", self.colors, "success", 65, 32, self._add_key).pack(side="left", padx=2)
        create_emoji_button(key_btn_frame, "Remove", "", self.colors, "danger", 78, 32, self._remove_key).pack(side="left", padx=2)
        create_emoji_button(key_btn_frame, "⬆", "", self.colors, "secondary", 35, 32, self._move_key_up).pack(side="left", padx=2)
        create_emoji_button(key_btn_frame, "⬇", "", self.colors, "secondary", 35, 32, self._move_key_down).pack(side="left", padx=2)

        # Track selected pool
        self._selected_pool_id = None

        # Populate pool list
        self._refresh_pool_list()

    # ------------------------------------------------------------------ #
    # Pool list helpers
    # ------------------------------------------------------------------ #

    def _pool_label(self, pool_id: str) -> str:
        """Format a pool ID for display in list widgets."""
        name = self._key_store.get_pool_display_name(pool_id)
        return f"{name} ({pool_id})" if name != pool_id else pool_id

    @staticmethod
    def _pool_label_for_id(key_store, pool_id: str) -> str:
        """Static helper matching ProviderTabMixin._pool_label_for."""
        name = key_store.get_pool_display_name(pool_id)
        return f"{name} ({pool_id})" if name != pool_id else pool_id

    def _refresh_pool_list(self):
        """Rebuild the pool list widget."""
        pool_list: ScrollableButtonList = self.widgets["keys_pool_list"]
        pool_list.clear()
        pools = self._key_store.list_pools()
        for p in pools:
            label = f"{p['display_name']}  ({p['key_count']})"
            pool_list.add_item(p["id"], label, "🗂️")

        # Re-select previous pool if still exists, otherwise select first
        if self._selected_pool_id and self._key_store.pool_exists(self._selected_pool_id):
            pool_list.select(self._selected_pool_id)
        elif pools:
            self._selected_pool_id = pools[0]["id"]
            pool_list.select(self._selected_pool_id)
            self._refresh_key_list()

    def _on_pool_selected(self, pool_id: str):
        """Handle pool selection."""
        self._selected_pool_id = pool_id
        self._refresh_key_list()

    def _refresh_key_list(self):
        """Rebuild the key list for the currently selected pool."""
        key_list: ScrollableButtonList = self.widgets["keys_key_list"]
        key_list.clear()

        if not self._selected_pool_id:
            self._keys_header_var.set("🔑 Keys")
            return

        display_name = self._key_store.get_pool_display_name(self._selected_pool_id)
        self._keys_header_var.set(f"🔑 Keys — {display_name}")

        keys_data = self._key_store.get_pool(self._selected_pool_id)
        for i, kd in enumerate(keys_data):
            masked = self._mask_key(kd)
            key_list.add_item(str(i), masked, "🔑")


    # ------------------------------------------------------------------ #
    # Pool CRUD
    # ------------------------------------------------------------------ #

    def _add_pool(self):
        """Add a new custom pool."""
        name = simpledialog.askstring(
            "New Key Pool", "Enter pool display name:",
            parent=self.root
        )
        if name and name.strip():
            new_id = self._key_store.add_pool(name.strip())
            self._selected_pool_id = new_id
            self._refresh_pool_list()
            self._refresh_key_list()

    def _rename_pool(self):
        """Rename the selected pool."""
        if not self._selected_pool_id:
            return
        current_name = self._key_store.get_pool_display_name(self._selected_pool_id)
        new_name = simpledialog.askstring(
            "Rename Pool", "Enter new display name:",
            initialvalue=current_name,
            parent=self.root
        )
        if new_name and new_name.strip():
            self._key_store.rename_pool(self._selected_pool_id, new_name.strip())
            self._refresh_pool_list()
            self._refresh_key_list()

    def _remove_pool(self):
        """Remove the selected pool (built-in pools cannot be removed)."""
        if not self._selected_pool_id:
            return
        if self._selected_pool_id in ("google", "openrouter", "custom"):
            return  # Built-in pools cannot be removed
        success = self._key_store.remove_pool(self._selected_pool_id)
        if success:
            self._selected_pool_id = None
            self._refresh_pool_list()
            self._refresh_key_list()

    # ------------------------------------------------------------------ #
    # Key CRUD within selected pool
    # ------------------------------------------------------------------ #

    def _add_key(self):
        """Add a key to the selected pool."""
        if not self._selected_pool_id:
            return
        key_var: tk.StringVar = self.widgets["keys_key_var"]
        name_var: tk.StringVar = self.widgets["keys_name_var"]
        key = key_var.get().strip()
        name = name_var.get().strip()
        if key:
            self._key_store.add_key(self._selected_pool_id, key, name)
            key_var.set("")
            name_var.set("")
            self._refresh_key_list()
            self._refresh_pool_list()  # Update key count in pool list

    def _remove_key(self):
        """Remove the selected key from the pool."""
        if not self._selected_pool_id:
            return
        key_list: ScrollableButtonList = self.widgets["keys_key_list"]
        selected = key_list.get_selected()
        if selected is not None:
            idx = int(selected)
            self._key_store.remove_key(self._selected_pool_id, idx)
            self._refresh_key_list()
            self._refresh_pool_list()

    def _move_key_up(self):
        """Move selected key up."""
        if not self._selected_pool_id:
            return
        key_list: ScrollableButtonList = self.widgets["keys_key_list"]
        selected = key_list.get_selected()
        if selected is not None:
            idx = int(selected)
            if idx > 0:
                self._key_store.reorder_key(self._selected_pool_id, idx, idx - 1)
                self._refresh_key_list()
                key_list.select(str(idx - 1))

    def _move_key_down(self):
        """Move selected key down."""
        if not self._selected_pool_id:
            return
        key_list: ScrollableButtonList = self.widgets["keys_key_list"]
        selected = key_list.get_selected()
        if selected is not None:
            idx = int(selected)
            keys_data = self._key_store.get_pool(self._selected_pool_id)
            if idx < len(keys_data) - 1:
                self._key_store.reorder_key(self._selected_pool_id, idx, idx + 1)
                self._refresh_key_list()
                key_list.select(str(idx + 1))

    # ------------------------------------------------------------------ #
    # Save — called by SettingsWindow save flow
    # ------------------------------------------------------------------ #

    def _save_keys_to_store(self):
        """Persist key changes and provider assignments to KeyStore.

        Called by the settings window's save handler.
        """
        # Apply provider → pool assignments (dropdowns live in Provider tab)
        provider_vars = self.widgets.get("keys_provider_pool_vars", {})
        for provider in ["google", "openrouter", "custom"]:
            entry = provider_vars.get(provider)
            if not entry:
                continue
            var, pool_ids = entry
            selected_label = var.get()
            for pid in pool_ids:
                if self._pool_label_for_id(self._key_store, pid) == selected_label:
                    self._key_store.set_provider_pool(provider, pid)
                    break

        self._key_store.save()

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #

    def _mask_key(self, key_data: dict) -> str:
        """Mask an API key for display, including name if present."""
        key = key_data.get("key", "")
        name = key_data.get("name", "")

        if len(key) <= 8:
            masked = "*" * len(key)
        else:
            masked = key[:4] + "…" + key[-4:]

        if name:
            return f"{masked}  ({name})"
        return masked
