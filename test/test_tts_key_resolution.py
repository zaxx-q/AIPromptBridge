#!/usr/bin/env python3
import threading
from unittest.mock import MagicMock, patch

import src.web_server as web_server
from src.connection_profiles import ConnectionProfile, ProfileStore
from src.gui.tts_tool import TTSToolApp
from src.key_manager import KeyManager
from src.key_store import KeyStore


def test_tts_official_endpoint_uses_google_pool_and_all_keys():
    """When tts_use_official_endpoint is True, TTS should always use the 'google' pool

    with all keys (no specific key filter) so key rotation works.
    """
    ProfileStore.reset_instance()
    KeyStore._instance = None
    key_store = KeyStore.get_instance()
    key_store._pools = {
        "google": {
            "display_name": "Google",
            "keys": [
                {"key": "gkey1", "name": "Google 1"},
                {"key": "gkey2", "name": "Google 2"},
            ],
        },
        "custom_pool": {
            "display_name": "Custom",
            "keys": [
                {"key": "ckey1", "name": "Custom 1"},
            ],
        },
    }
    key_store._obfuscation_disabled = True

    # Active profile sets a custom pool and specific key name
    active_profile = ConnectionProfile(
        provider="google",
        model="gemini-2.5-flash",
        api_key_pool="custom_pool",
        api_key_name="Custom 1",
    )
    web_server.ACTIVE_PROFILE = active_profile
    web_server.SESSION_OVERRIDES = {}

    config = {
        "tts_enabled": True,
        "tts_use_official_endpoint": True,
    }
    ai_params = {}
    base_km = KeyManager(["dummy_key"], "google")

    app = TTSToolApp(config=config, ai_params=ai_params, key_managers={"google": base_km})

    captured_provider_args = {}
    done_event = threading.Event()

    mock_provider = MagicMock()
    mock_provider.generate_tts.return_value = (b"pcm_bytes_1234", None)

    def mock_create_provider(provider_type, key_manager, provider_config):
        captured_provider_args["provider_type"] = provider_type
        captured_provider_args["key_manager"] = key_manager
        captured_provider_args["provider_config"] = provider_config
        return mock_provider

    def on_success(pcm, wav, dur):
        done_event.set()

    def on_error(err):
        done_event.set()

    with patch("src.gui.tts_tool.create_provider", side_effect=mock_create_provider):
        app.generate_audio(
            text="Hello world",
            voice_name="Puck",
            model="gemini-2.5-flash",
            callback_success=on_success,
            callback_error=on_error,
        )
        assert done_event.wait(timeout=5)

    assert captured_provider_args["provider_type"] == "google"
    km = captured_provider_args["key_manager"]
    assert km is not None
    # Key manager should contain ALL keys from the google pool (gkey1, gkey2) for rotation
    assert km.keys == ["gkey1", "gkey2"]
    assert km.key_names == ["Google 1", "Google 2"]
    assert captured_provider_args["provider_config"].get("tts_use_official_endpoint") is True


def test_tts_official_endpoint_ignores_non_google_active_profile():
    """When tts_use_official_endpoint is True and active profile is OpenAI/Anthropic,

    TTS should still use the 'google' pool and not fail or use the wrong provider key.
    """
    ProfileStore.reset_instance()
    KeyStore._instance = None
    key_store = KeyStore.get_instance()
    key_store._pools = {
        "google": {
            "display_name": "Google",
            "keys": [
                {"key": "gkey_official", "name": "Official Google Key"},
            ],
        },
        "openai": {
            "display_name": "OpenAI",
            "keys": [
                {"key": "sk-openai", "name": "OpenAI Key"},
            ],
        },
    }
    key_store._obfuscation_disabled = True

    active_profile = ConnectionProfile(
        provider="openai",
        model="gpt-4o",
        api_key_pool="openai",
        api_key_name="OpenAI Key",
    )
    web_server.ACTIVE_PROFILE = active_profile
    web_server.SESSION_OVERRIDES = {}

    config = {
        "tts_enabled": True,
        "tts_use_official_endpoint": True,
    }
    ai_params = {}
    base_km = KeyManager(["dummy_key"], "google")

    app = TTSToolApp(config=config, ai_params=ai_params, key_managers={"google": base_km})

    captured_provider_args = {}
    done_event = threading.Event()

    mock_provider = MagicMock()
    mock_provider.generate_tts.return_value = (b"pcm_bytes_5678", None)

    def mock_create_provider(provider_type, key_manager, provider_config):
        captured_provider_args["provider_type"] = provider_type
        captured_provider_args["key_manager"] = key_manager
        captured_provider_args["provider_config"] = provider_config
        return mock_provider

    def on_success(pcm, wav, dur):
        done_event.set()

    def on_error(err):
        done_event.set()

    with patch("src.gui.tts_tool.create_provider", side_effect=mock_create_provider):
        app.generate_audio(
            text="Hello world",
            voice_name="Puck",
            model="gemini-2.5-flash",
            callback_success=on_success,
            callback_error=on_error,
        )
        assert done_event.wait(timeout=5)

    assert captured_provider_args["provider_type"] == "google"
    km = captured_provider_args["key_manager"]
    assert km is not None
    assert km.keys == ["gkey_official"]
    assert km.key_names == ["Official Google Key"]


def test_tts_custom_endpoint_uses_active_profile_override():
    """When tts_use_official_endpoint is False, TTS should use the active profile's

    specific key pool/name and base_url.
    """
    ProfileStore.reset_instance()
    KeyStore._instance = None
    key_store = KeyStore.get_instance()
    key_store._pools = {
        "google": {
            "display_name": "Google",
            "keys": [
                {"key": "gkey_default", "name": "Default Google Key"},
            ],
        },
        "custom_proxy_pool": {
            "display_name": "Custom Proxy",
            "keys": [
                {"key": "proxy_key_1", "name": "Key 1"},
                {"key": "proxy_key_2", "name": "Key 2"},
            ],
        },
    }
    key_store._obfuscation_disabled = True

    active_profile = ConnectionProfile(
        provider="google",
        model="gemini-2.5-flash",
        base_url="https://custom.proxy.endpoint/v1",
        api_key_pool="custom_proxy_pool",
        api_key_name="Key 2",
    )
    web_server.ACTIVE_PROFILE = active_profile
    web_server.SESSION_OVERRIDES = {}

    config = {
        "tts_enabled": True,
        "tts_use_official_endpoint": False,
    }
    ai_params = {}
    base_km = KeyManager(["gkey_default"], "google")

    app = TTSToolApp(config=config, ai_params=ai_params, key_managers={"google": base_km})

    captured_provider_args = {}
    done_event = threading.Event()

    mock_provider = MagicMock()
    mock_provider.generate_tts.return_value = (b"pcm_bytes_9999", None)

    def mock_create_provider(provider_type, key_manager, provider_config):
        captured_provider_args["provider_type"] = provider_type
        captured_provider_args["key_manager"] = key_manager
        captured_provider_args["provider_config"] = provider_config
        return mock_provider

    def on_success(pcm, wav, dur):
        done_event.set()

    def on_error(err):
        done_event.set()

    with patch("src.gui.tts_tool.create_provider", side_effect=mock_create_provider):
        app.generate_audio(
            text="Hello world",
            voice_name="Puck",
            model="gemini-2.5-flash",
            callback_success=on_success,
            callback_error=on_error,
        )
        assert done_event.wait(timeout=5)

    assert captured_provider_args["provider_type"] == "google"
    km = captured_provider_args["key_manager"]
    assert km is not None
    # Key manager should only have the single selected key from the custom pool
    assert km.keys == ["proxy_key_2"]
    assert captured_provider_args["provider_config"].get("base_url") == "https://custom.proxy.endpoint/v1"
    assert captured_provider_args["provider_config"].get("tts_use_official_endpoint") is False
