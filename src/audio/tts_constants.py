#!/usr/bin/env python3
"""
Constants for Text-to-Speech (TTS) feature.
Contains static voice definitions and model lists.
"""

# Gemini TTS Models
TTS_MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts"
]

# Gemini TTS Voices
# Format: Name -> {style, gender}
TTS_VOICES = {
    "Puck": {"style": "Upbeat", "gender": "Male"},
    "Charon": {"style": "Informative", "gender": "Male"},
    "Kore": {"style": "Firm", "gender": "Female"},
    "Fenrir": {"style": "Excitable", "gender": "Male"},
    "Aoede": {"style": "Breezy", "gender": "Female"},
    "Zephyr": {"style": "Bright", "gender": "Female"},
    "Leda": {"style": "Youthful", "gender": "Female"},
    "Orus": {"style": "Firm", "gender": "Male"},
    "Callirrhoe": {"style": "Easy-going", "gender": "Female"},
    "Autonoe": {"style": "Bright", "gender": "Female"},
    "Enceladus": {"style": "Breathy", "gender": "Male"},
    "Iapetus": {"style": "Clear", "gender": "Male"},
    "Umbriel": {"style": "Easy-going", "gender": "Male"},
    "Algieba": {"style": "Smooth", "gender": "Male"},
    "Despina": {"style": "Smooth", "gender": "Female"},
    "Erinome": {"style": "Clear", "gender": "Female"},
    "Algenib": {"style": "Gravelly", "gender": "Male"},
    "Rasalgethi": {"style": "Informative", "gender": "Male"},
    "Laomedeia": {"style": "Upbeat", "gender": "Female"},
    "Achernar": {"style": "Soft", "gender": "Female"},
    "Alnilam": {"style": "Firm", "gender": "Male"},
    "Schedar": {"style": "Even", "gender": "Male"},
    "Gacrux": {"style": "Mature", "gender": "Female"},
    "Pulcherrima": {"style": "Forward", "gender": "Female"},
    "Achird": {"style": "Friendly", "gender": "Male"},
    "Zubenelgenubi": {"style": "Casual", "gender": "Male"},
    "Vindemiatrix": {"style": "Gentle", "gender": "Female"},
    "Sadachbia": {"style": "Lively", "gender": "Male"},
    "Sadaltager": {"style": "Knowledgeable", "gender": "Male"},
    "Sulafat": {"style": "Warm", "gender": "Female"}
}

def get_voice_list() -> list[str]:
    """Get formatted list of voices (Name - Gender, Style)."""
    return [
        f"{name} — {data['gender']}, {data['style']}"
        for name, data in TTS_VOICES.items()
    ]

def get_voice_details(name: str) -> dict:
    """Get details for a specific voice."""
    return TTS_VOICES.get(name, {"style": "Unknown", "gender": "Unknown"})
