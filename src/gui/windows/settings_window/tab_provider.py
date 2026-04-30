#!/usr/bin/env python3
"""
Provider tab mixin for Settings Window.

Sections:
    🥇 Default Provider — provider selector dropdown
    🛠️ Custom Provider — URL + model
    🚀 OpenRouter — model
    💎 Google Gemini — model + gemini_endpoint
    🔄 Request Settings — retries, delay, timeout
"""

import tkinter as tk

from ...platform import HAVE_CTK, ctk
from ...themes import get_ctk_font, get_ctk_label_colors
from ...custom_widgets import create_section_header


class ProviderTabMixin:
    """Mixin providing the Provider tab for SettingsWindow."""

    def _create_provider_tab(self, frame):
        """Create the Provider settings tab."""
        content = self._create_tab_scroll_frame(frame)

        # --- Default Provider ---
        create_section_header(content, "🥇 Default Provider", self.colors)

        self._add_dropdown_field(content, "default_provider", "Provider:",
                                 self.config_data.config.get("default_provider", "google"),
                                 options=["custom", "openrouter", "google"], size="md",
                                 hint="Selected provider for API calls")

        # --- Custom Provider ---
        create_section_header(content, "🛠️ Custom Provider", self.colors, top_padding=20)

        self._add_entry_field(content, "custom_url", "URL:",
                             self.config_data.config.get("custom_url", "") or "",
                             size="lg", hint="OpenAI-compatible endpoint URL")

        self._add_model_dropdown_field(content, "custom_model", "Model:",
                                       self.config_data.config.get("custom_model", "") or "",
                                       provider="custom")

        # --- OpenRouter ---
        create_section_header(content, "🚀 OpenRouter", self.colors, top_padding=20)

        self._add_model_dropdown_field(content, "openrouter_model", "Model:",
                                       self.config_data.config.get("openrouter_model", ""),
                                       provider="openrouter")

        # --- Google Gemini ---
        create_section_header(content, "💎 Google Gemini", self.colors, top_padding=20)

        self._add_model_dropdown_field(content, "google_model", "Model:",
                                       self.config_data.config.get("google_model", ""),
                                       provider="google")

        self._add_entry_field(content, "gemini_endpoint", "Custom endpoint:",
                             self.config_data.config.get("gemini_endpoint", "") or "",
                             size="lg",
                             hint="Custom Gemini API base URL (empty = official Google endpoint)")

        # --- Request Settings (moved from General > Limits) ---
        create_section_header(content, "🔄 Request Settings", self.colors, top_padding=20)

        self._add_spinbox_field(content, "max_retries", "Max retries:",
                               self.config_data.config.get("max_retries", 3),
                               0, 10, hint="Retries before giving up on API calls")

        self._add_spinbox_field(content, "retry_delay", "Retry delay (s):",
                               self.config_data.config.get("retry_delay", 5),
                               1, 60, hint="Seconds between retries")

        self._add_spinbox_field(content, "request_timeout", "Request timeout (s):",
                               self.config_data.config.get("request_timeout", 120),
                               10, 600, hint="Timeout for API requests")

    # -------------------------------------------------------------------------
    # Model fetching helpers (used by _add_model_dropdown_field)
    # -------------------------------------------------------------------------

    def _collect_ui_values_for_provider(self, provider: str) -> dict:
        """
        Collect current UI values needed for model fetching.
        Must be called from the main thread before starting background work.
        """
        result = {"custom_url": None, "keys": [], "error": None}

        if provider == "custom":
            custom_url_var = self.vars.get("custom_url")
            if custom_url_var:
                try:
                    result["custom_url"] = custom_url_var.get()
                except tk.TclError:
                    result["error"] = "Could not read custom URL"
                    return result
            else:
                result["error"] = "Custom URL not configured"
                return result

        # Get keys from UI if tab has been loaded, otherwise fall back to parsed config
        keys_data = self.widgets.get(f"keys_{provider}_data")
        if keys_data is None:
            keys_data = self.config_data.keys.get(provider, [])
        if not keys_data:
            result["error"] = f"No API keys configured for {provider}"
            return result

        for kd in keys_data:
            key_str = kd.get("key", "")
            if key_str:
                result["keys"].append(key_str)

        if not result["keys"]:
            result["error"] = f"No valid API keys for {provider}"

        return result

    def _fetch_models_with_values(self, provider: str, ui_values: dict) -> tuple:
        """
        Fetch models using pre-collected UI values.
        Safe to call from a background thread.
        """
        if ui_values.get("error"):
            return [], ui_values["error"]

        key_strings = ui_values.get("keys", [])
        if not key_strings:
            return [], f"No valid API keys for {provider}"

        temp_config = {"request_timeout": 30}
        if provider == "custom" and ui_values.get("custom_url"):
            temp_config["custom_url"] = ui_values["custom_url"]

        try:
            from ....key_manager import KeyManager
            temp_key_manager = KeyManager(key_strings, provider)

            from ....api_client import get_provider_for_type
            provider_instance = get_provider_for_type(provider, temp_key_manager, temp_config)
            models, error = provider_instance.fetch_models()

            if error:
                return [], error
            if not models:
                return [], "No models returned"

            return [m.get("id", str(m)) for m in models], None
        except Exception as e:
            return [], f"Error fetching models: {e}"

    def _refresh_models(self, provider: str, dropdown_widget, status_label):
        """Refresh models in background thread, update dropdown when done."""
        import threading

        ui_values = self._collect_ui_values_for_provider(provider)

        if ui_values.get("error"):
            if self.use_ctk:
                status_label.configure(text=f"❌ {ui_values['error'][:35]}", text_color=self.colors.accent_red)
            else:
                status_label.configure(text=f"Error: {ui_values['error'][:35]}", fg=self.colors.accent_red)
            return

        if self.use_ctk:
            status_label.configure(text="🔄 Loading...", text_color=self.colors.accent)
        else:
            status_label.configure(text="Loading...", fg=self.colors.accent)

        def fetch_thread():
            models, error = self._fetch_models_with_values(provider, ui_values)
            if self.root and not self._destroyed:
                self._schedule_callback(lambda: self._update_model_dropdown(
                    provider, dropdown_widget, status_label, models, error
                ))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_model_dropdown(self, provider, dropdown_widget, status_label, models, error):
        """Update model dropdown after fetch completes."""
        if self._destroyed:
            return

        if error:
            if self.use_ctk:
                status_label.configure(text=f"❌ {error[:40]}", text_color=self.colors.accent_red)
            else:
                status_label.configure(text=f"Error: {error[:40]}", fg=self.colors.accent_red)
            return

        if not models:
            if self.use_ctk:
                status_label.configure(text="⚠️ No models found", text_color=self.colors.accent_yellow)
            else:
                status_label.configure(text="No models found", fg=self.colors.accent_yellow)
            return

        if self.use_ctk:
            dropdown_widget.configure(values=models)
            status_label.configure(text=f"✅ {len(models)} models", text_color=self.colors.accent_green)
        else:
            dropdown_widget.configure(values=models)
            status_label.configure(text=f"{len(models)} models", fg=self.colors.accent_green)
