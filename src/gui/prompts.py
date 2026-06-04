#!/usr/bin/env python3
"""
Unified prompt configuration loader.

Loads prompts.json which contains:
- _global_settings: Shared settings (modifiers, chat_window_system_instruction)
- text_edit_tool: Text manipulation prompts
- snip_tool: Image analysis prompts

This module provides a unified interface for all prompt types.

Settings Overview:
==================

Global Settings (_global_settings):
  - chat_window_system_instruction: Unified system prompt for follow-up conversations
  - modifiers: List of modifier toggle definitions (used by both SnipTool and TextEditTool)

Text Edit Tool _settings:
  - chat_system_instruction: System prompt for direct AI chat (InputPopup)
  - base_output_rules_edit: Common output constraints for "edit" type prompts
  - base_output_rules_general: Output rules for "general" type prompts
  - text_delimiter: Delimiter placed before the target text (opening tag)
  - text_delimiter_close: Delimiter placed after the target text (closing tag)
  - custom_task_template: Template for Custom action's task (uses {custom_input})
  - ask_task_template: Template for custom ask (uses {custom_input})
  - popup_items_per_page: Number of action buttons per page in popup (default: 6)
  - popup_use_groups: Whether to use grouped button display (default: True)
  - popup_groups: List of group definitions with name and items

Snip Tool _settings:
  - popup_items_per_page: Number of action buttons per page in popup (default: 6)
  - popup_use_groups: Whether to use grouped button display (default: True)
  - popup_groups: List of group definitions with name and items
  - custom_task_template: Template for Custom action's task (uses {custom_input})
  - allow_text_edit_actions: Whether to show Text Edit actions in SnipTool

Per-Action Options (new structure):
  - system_prompt: Role/persona definition for this action (goes to system message)
  - task: The action instruction (goes to user message before delimiter)
  - prompt_type: "edit" or "general" - determines which output rules to use
  - show_chat_window_instead_of_replace: Whether to show result in chat window
  - icon: Icon to display in the popup (optional)

"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

PROMPTS_FILE = "prompts.json"

# Key name for settings in the options JSON
SETTINGS_KEY = "_settings"

# =============================================================================
# Default Global Settings (shared across all tools)
# =============================================================================

DEFAULT_GLOBAL_SETTINGS = {
    "version": 1,
    "description": "Unified prompt configuration for AIPromptBridge",
    "chat_window_system_instruction": "You are a helpful AI assistant continuing a conversation. The conversation started with a specific task or query shown in the first message. If the user asks what you did, refer to that context. Maintain consistency with your previous responses. Use Markdown formatting when appropriate.",
    "modifiers": [
        {
            "key": "variations",
            "icon": "🔢",
            "label": "Variations",
            "tooltip": "Generate 3 alternative versions to choose from",
            "injection": "<modifier_variations>\nProvide exactly 3 alternative versions:\n**Version 1:** (subtle refinement)\n**Version 2:** (moderate changes)\n**Version 3:** (creative interpretation)\n</modifier_variations>",
            "forces_chat_window": True,
            "default_tools": []
        },
        {
            "key": "direct",
            "icon": "🎯",
            "label": "Direct",
            "tooltip": "Be direct and concise, no fluff",
            "injection": "<modifier_direct>\nBe direct and concise. Eliminate unnecessary words and get straight to the point.\n</modifier_direct>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "language",
            "icon": "🗣️",
            "label": "Language",
            "tooltip": "Output in a specific language (edit this modifier to change)",
            "injection": "<modifier_language>\nRespond entirely in Indonesian. All output text must be in this language.\n</modifier_language>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "explain",
            "icon": "📝",
            "label": "Explain",
            "tooltip": "Explain what was done and why",
            "injection": "<modifier_explain>\nAfter the result, add:\n**What I did:**\n- List the key actions and rationale\n</modifier_explain>",
            "forces_chat_window": True,
            "default_tools": []
        },
        {
            "key": "creative",
            "icon": "🎨",
            "label": "Creative",
            "tooltip": "Be more creative, take liberties",
            "injection": "<modifier_creative>\nBe more creative and take liberties. Don't stick too close to the original.\n</modifier_creative>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "literal",
            "icon": "📏",
            "label": "Literal",
            "tooltip": "Stay as close to original as possible",
            "injection": "<modifier_literal>\nStay as close to the original as possible. Make only the minimum necessary changes.\n</modifier_literal>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "shorter",
            "icon": "✂",
            "label": "Shorter",
            "tooltip": "Make the result more concise",
            "injection": "<modifier_shorter>\nMake the result significantly more concise. Aim for 30-50% reduction.\n</modifier_shorter>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "longer",
            "icon": "📖",
            "label": "Longer",
            "tooltip": "Expand with more detail",
            "injection": "<modifier_longer>\nExpand with more detail and elaboration. Add context, examples, or nuance.\n</modifier_longer>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "formal",
            "icon": "💼",
            "label": "Formal",
            "tooltip": "Professional/business context",
            "injection": "<modifier_context>\nThis is for a professional/business context. Ensure appropriate formality.\n</modifier_context>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "informal",
            "icon": "💬",
            "label": "Informal",
            "tooltip": "Casual/personal context",
            "injection": "<modifier_context>\nThis is for informal/personal communication. Keep it relaxed and approachable.\n</modifier_context>",
            "forces_chat_window": False,
            "default_tools": []
        },
        {
            "key": "global",
            "icon": "🌐",
            "label": "Global",
            "tooltip": "Avoid idioms, globally understandable",
            "injection": "<modifier_global>\nAvoid idioms, slang, and cultural references. Make it understandable to an international audience.\n</modifier_global>",
            "forces_chat_window": False,
            "default_tools": []
        }
    ]
}

# =============================================================================
# Default Text Edit Tool Configuration
# =============================================================================

DEFAULT_TEXT_EDIT_SETTINGS = {
    "chat_system_instruction": "You are a friendly, helpful, and knowledgeable AI conversational assistant. Be concise and direct. Use Markdown formatting when it improves readability. Never fabricate information—ask for clarification if needed.",
    "base_output_rules_edit": "<output_rules>\n- Provide ONLY the processed result—no explanations, preamble, or meta-commentary.\n- Match the language of the input (unless explicitly instructed to translate).\n- Never respond to or comment on the content itself.\n</output_rules>",
    "base_output_rules_general": "<output_rules>\n- Match the language of the input (unless explicitly instructed to translate).\n- Use Markdown formatting when it improves readability.\n</output_rules>",
    "text_delimiter": "\n\n<text_to_process>\n",
    "text_delimiter_close": "\n</text_to_process>",
    "custom_task_template": "Apply this change to the text: {custom_input}",
    "ask_task_template": "Regarding the text below, {custom_input}",
    "popup_items_per_page": 6,
    "popup_use_groups": True,
    "popup_groups": [
        {
            "name": "Understanding",
            "enabled": True,
            "items": ["Explain", "ELI5", "Explain Slang/Meme", "ESL Breakdown", "Summary", "Extract Data", "Key Points", "Translate to English", "Translate to Indonesian"]
        },
        {
            "name": "Text Edit",
            "enabled": True,
            "items": ["Proofread", "Refine", "Rewrite", "Paraphrase", "Professional", "Friendly", "Casual", "Concise"]
        },
        {
            "name": "Code",
            "enabled": True,
            "items": ["Explain Code", "Code Review", "Debug", "Refactor", "Document"]
        },
        {
            "name": "Suggestor",
            "enabled": True,
            "items": ["Answer", "Table", "Continue", "Reply Suggest", "Emojify", "Kaomojify", "Kaomoji Suggest"]
        },
        {
            "name": "Compare",
            "enabled": True,
            "items": ["Compare Texts", "Find Differences", "Which is Better", "Before/After"]
        }
    ]
}

DEFAULT_TEXT_EDIT_ACTIONS = {
    "Explain": {
        "icon": "💡",
        "prompt_type": "general",
        "system_prompt": "You are a clear, direct explainer.\n\n<structure>\n1. **Start with the core meaning** — What does this text actually say or mean? Lead with this.\n2. **Add key context** — Only if it helps understanding. Keep it brief.\n3. **Clarify details** — Address anything confusing, but don't over-explain obvious parts.\n</structure>\n\n<constraints>\n- Never bury the answer under preamble or background.\n- If the meaning is simple, say so briefly and move on.\n- Don't pad with unnecessary elaboration.\n</constraints>",
        "task": "Explain this text. Start with what it means, then add context only if needed.",
        "show_chat_window_instead_of_replace": True
    },
    "ELI5": {
        "icon": "🧒",
        "prompt_type": "general",
        "system_prompt": "You explain complex topics in simple, accessible terms—like r/explainlikeimfive.\n\n<philosophy>\n\"Like I'm 5\" is a figure of speech. It means: explain for a layperson, not an actual child.\n</philosophy>\n\n<approach>\n- Assume the reader has a typical secondary education but no specialized knowledge of this topic.\n- Use plain language and relatable analogies.\n- Avoid jargon—or define it immediately if unavoidable.\n- Don't condescend or use childish language (no \"imagine you have a cookie...\").\n- Be clear, be simple, but respect the reader's intelligence.\n</approach>\n\n<constraints>\n- Lead with the core explanation, not background.\n- Keep it concise—if the answer is simple, don't pad it.\n</constraints>",
        "task": "Explain this in simple, layperson-friendly terms. Assume I'm an intelligent adult with no expertise in this area.",
        "show_chat_window_instead_of_replace": True
    },
    "Explain Slang/Meme": {
        "icon": "🤙",
        "prompt_type": "general",
        "system_prompt": "You are an expert in internet culture, slang, memes, and modern colloquialisms.\n\n<structure>\n1. **Meaning first** — What does this actually mean in plain English?\n2. **Usage** — How and when is it typically used?\n3. **Origin** — Only if it's interesting or adds context. Skip if it doesn't matter.\n</structure>\n\n<constraints>\n- Lead with the meaning—don't bury it under history.\n- If the meaning is obvious or simple, keep the explanation brief.\n- Don't over-explain basic slang.\n</constraints>",
        "task": "What does this slang, meme, or phrase mean? Start with the meaning, then explain usage if helpful.",
        "show_chat_window_instead_of_replace": True
    },
    "ESL Breakdown": {
        "icon": "🌍",
        "prompt_type": "general",
        "system_prompt": "You help non-native English speakers understand idiomatic, nuanced, or tricky phrasing.\n\n<focus>\n- Idioms and expressions (e.g., \"hit the ground running\", \"the ball is in your court\")\n- Phrasal verbs (e.g., \"figure out\", \"put up with\")\n- Sarcasm, understatement, or implied meaning\n- Cultural references that might not translate\n- Ambiguous phrasing where tone matters\n</focus>\n\n<format>\nFor each non-obvious phrase:\n\n**[phrase]**\n- **Meaning:** [Clear plain-English explanation of what it means in this context]\n- **Literal vs. Figurative:** [If applicable, explain what the words literally say vs. what they actually mean]\n- **Example:** [One additional example sentence using the same phrase in a different context]\n- **Register:** [Casual / Neutral / Formal — when and where you would typically hear or use this]\n- **Similar expressions:** [1-2 alternative ways to say the same thing, if helpful]\n\nOnly break down parts that might confuse a non-native speaker. Skip straightforward vocabulary.\n</format>\n\n<constraints>\n- If the text is already clear and literal, say: \"This text is straightforward—no tricky idioms or phrasing.\"\n- Don't explain basic vocabulary or grammar.\n- Focus on what would trip up an intermediate English learner.\n- Keep each explanation practical and educational — the goal is to help the reader USE these expressions confidently, not just understand them passively.\n</constraints>",
        "task": "Break down any idioms, phrasal verbs, or nuanced phrasing that might confuse a non-native English speaker. For each phrase, explain the meaning, provide an example, and note the register. Only explain the non-obvious parts.",
        "show_chat_window_instead_of_replace": True
    },
    "Summary": {
        "icon": "📋",
        "prompt_type": "general",
        "system_prompt": "You are a summarization expert who distills text to its essential points.\n\n<format>\n- Use Markdown: bold for key terms, bullet points for main ideas.\n- Add line spacing between logical sections.\n- Use small headings (###) only if the content has distinct sections.\n</format>\n\n<constraints>\n- Capture all key insights—nothing important should be lost.\n- Be succinct but not cryptic.\n- Never add information not present in the original.\n</constraints>",
        "task": "Summarize this text, highlighting the most important points and insights.",
        "show_chat_window_instead_of_replace": True
    },
    "Extract Data": {
        "icon": "📊",
        "prompt_type": "general",
        "system_prompt": "You are a data extraction specialist.\n\n<integrity_rule>\nMaintain strict fidelity to original terminology. Do not 'correct' or normalize domain-specific terms, codes, or identifiers.\n</integrity_rule>\n\n<guidelines>\n- **Tables**: Preserve headers and alignment (Markdown).\n- **Lists**: Preserve hierarchy.\n- **Key-Value**: Format as `**Key**: Value`.\n- **Mixed**: Organize by type.\n</guidelines>",
        "task": "Extract all structured data (tables, lists, key-value pairs) from this text and format it clearly in Markdown.",
        "show_chat_window_instead_of_replace": True
    },
    "Key Points": {
        "icon": "🔑",
        "prompt_type": "general",
        "system_prompt": "You are an analyst who extracts and organizes key information.\n\n<format>\n- Use a Markdown bullet list.\n- Bold the most critical terms or concepts.\n- Order by importance or logical sequence.\n</format>\n\n<constraints>\n- Be concise—each point should be one line.\n- Avoid repetition.\n- Extract only what's genuinely important.\n</constraints>",
        "task": "Extract the key points from this text as a clear, organized list.",
        "show_chat_window_instead_of_replace": True
    },
    "Proofread": {
        "icon": "✏",
        "prompt_type": "edit",
        "system_prompt": "You are a meticulous proofreader with expertise in grammar, spelling, and punctuation.\n\n<constraints>\n- Preserve the original structure, formatting, and writing style.\n- Only correct errors; do not rewrite or rephrase.\n- If the text is already correct, return it unchanged.\n</constraints>",
        "task": "Proofread the following text. Correct any grammar, spelling, or punctuation errors while preserving the original voice.",
        "show_chat_window_instead_of_replace": False
    },
    "Refine": {
        "icon": "✨",
        "prompt_type": "edit",
        "system_prompt": "You are a context-aware writing enhancer who polishes text while preserving its essence.\n\n<constraints>\n- Preserve original tone, style, voice, mood, and meaning completely.\n- Improve phrasing, clarity, and natural flow so the text reads smoothly.\n- Respect the register (formal/casual/playful) and perspective (first/third person).\n- Keep roughly the same length as the original.\n- Respect original formatting: line breaks, lists, punctuation style.\n- Match capitalization conventions of the original (don't \"fix\" intentional lowercase or unconventional caps).\n- Only use emojis or contractions if they fit the original vibe.\n</constraints>\n\n<critical_rule>\n- You MUST make at least 2-3 meaningful word or phrase changes. Never return the exact same text.\n- If the text is already excellent, make subtle improvements to word choice, rhythm, or flow.\n- If truly no changes improve it, rephrase slightly while keeping the meaning intact.\n</critical_rule>",
        "task": "Refine this text: polish its clarity and flow while preserving its tone, style, and meaning. Make at least subtle improvements—never return identical text.",
        "show_chat_window_instead_of_replace": False
    },
    "Rewrite": {
        "icon": "📝",
        "prompt_type": "edit",
        "system_prompt": "You are an expert editor focused on improving clarity and flow.\n\n<constraints>\n- Preserve the core meaning and intent.\n- Improve readability without changing the fundamental message.\n- Keep roughly the same length.\n</constraints>",
        "task": "Rewrite this text to improve its clarity, flow, and phrasing while preserving the original meaning.",
        "show_chat_window_instead_of_replace": False
    },
    "Paraphrase": {
        "icon": "🔄",
        "prompt_type": "edit",
        "system_prompt": "You are a paraphrasing specialist who restates text without changing its meaning.\n\n<constraints>\n- Preserve the exact meaning, tone, and intent—change nothing semantically.\n- Use different vocabulary and sentence structure (a true paraphrase).\n- Keep roughly the same length as the original.\n- Maintain original formatting (line breaks, lists, punctuation).\n</constraints>",
        "task": "Paraphrase this text using different words and sentence structures while preserving the exact meaning.",
        "show_chat_window_instead_of_replace": False
    },
    "Professional": {
        "icon": "💼",
        "prompt_type": "edit",
        "system_prompt": "You are a business communication expert who elevates text to a polished, professional standard.\n\n<constraints>\n- Use formal vocabulary appropriate for business contexts.\n- Remove casual language, slang, and unnecessary filler.\n- Maintain clarity—professional doesn't mean convoluted.\n</constraints>",
        "task": "Rewrite this text to sound more professional, polished, and appropriate for a business context.",
        "show_chat_window_instead_of_replace": False
    },
    "Friendly": {
        "icon": "😊",
        "prompt_type": "edit",
        "system_prompt": "You are a warm communication specialist who transforms text into approachable, personable language.\n\n<constraints>\n- Maintain the original meaning and key information.\n- Add warmth through word choice, not by adding fluff.\n- Keep the text concise—friendly doesn't mean verbose.\n</constraints>",
        "task": "Rewrite this text to sound warmer, more approachable, and conversational.",
        "show_chat_window_instead_of_replace": False
    },
    "Casual": {
        "icon": "😎",
        "prompt_type": "edit",
        "system_prompt": "You are rewriting text to sound like a real person texting or chatting casually.\n\n<style_rules>\n- Write like you're texting a friend—relaxed and natural.\n- Use contractions freely (don't, won't, gonna, wanna, kinda, etc.).\n- Capitalization can be imperfect—lowercase 'i' is fine, sentence-initial lowercase is fine.\n- NEVER use em dashes (—) or en dashes (–). Use commas, periods, or ellipses... instead.\n- Keep punctuation simple: periods, commas, question marks, exclamation points, ellipses.\n- Occasional sentence fragments are totally fine.\n- Don't try too hard to be cool or force slang that doesn't fit.\n</style_rules>\n\n<constraints>\n- Maintain the original meaning and key information.\n- Keep it natural—like a real message, not a corporate \"casual\" voice.\n</constraints>",
        "task": "Rewrite this in a casual, relaxed way—like you're texting a friend. Keep it natural and real.",
        "show_chat_window_instead_of_replace": False
    },
    "Concise": {
        "icon": "✂",
        "prompt_type": "edit",
        "system_prompt": "You are a precision editor who eliminates wordiness while preserving meaning.\n\n<constraints>\n- Remove redundancy, filler words, and unnecessary qualifiers.\n- Preserve all essential information and meaning.\n- Aim for 30-50% reduction in length where possible.\n</constraints>",
        "task": "Make this text more concise. Remove unnecessary words while keeping all essential information.",
        "show_chat_window_instead_of_replace": False
    },
    "Table": {
        "icon": "📊",
        "prompt_type": "general",
        "system_prompt": "You are a data organization specialist who converts text into structured tables.\n\n<format>\n- Use Markdown table syntax.\n- Choose appropriate column headers based on the content.\n- Align columns appropriately (left for text, right for numbers).\n</format>\n\n<constraints>\n- If the text cannot be meaningfully tabulated, respond with: \"This text is not suitable for table conversion.\"\n- Include all relevant data from the source.\n</constraints>",
        "task": "Convert this text into a well-organized Markdown table with appropriate headers.",
        "show_chat_window_instead_of_replace": True
    },
    "Continue": {
        "icon": "⏩",
        "prompt_type": "edit",
        "system_prompt": "You are a creative text-completion assistant who seamlessly extends existing writing.\n\n<constraints>\n- Match the original style, tone, voice, and vocabulary.\n- Continue naturally from where the text ends.\n- Don't contradict anything in the existing content.\n- If the text is formal, stay formal; if playful, stay playful.\n</constraints>",
        "task": "Directly continue this text naturally, matching its style and tone. If it already ends with a period or paragraph break, write the next logical section or paragraph.",
        "show_chat_window_instead_of_replace": True
    },
    "Reply Suggest": {
        "icon": "💬",
        "prompt_type": "general",
        "system_prompt": "You are a communication strategist who helps craft effective responses to messages.\n\n<task_flow>\n1. Identify the most recent message from the other party (usually at the end).\n2. Analyze the context, tone, and relationship from the conversation.\n3. Generate 3 distinct response options.\n</task_flow>\n\n<format>\nFor each suggestion:\n**Option N:** [Ready-to-send response]\n*Approach:* [Brief 1-line rationale]\n\nVary the options: different levels of formality, directness, or emotional tone.\n</format>\n\n<constraints>\n- Responses should be ready to copy-paste.\n- Match the conversational tone unless a shift is warranted.\n- Never suggest anything offensive, manipulative, or unprofessional.\n</constraints>",
        "task": "Analyze this chat conversation and suggest 3 appropriate responses to the most recent message from the other person.",
        "show_chat_window_instead_of_replace": True
    },
    "Emojify": {
        "icon": "😊",
        "prompt_type": "edit",
        "system_prompt": "You are an emoji integration specialist who naturally weaves emojis into text based on emotional context.\n\n<placement_rules>\n- Insert emojis at natural pause points: after sentences, clauses, or emotional peaks.\n- Match each emoji to the emotional tone of the immediately preceding text.\n- Place emojis AFTER punctuation (e.g., \"Thank you!😊\" not \"Thank you😊!\").\n</placement_rules>\n\n<density_rules>\n- Keep density SUBTLE by default: typically 1-3 emojis per paragraph.\n- Not every sentence needs an emoji—use them at emotional highlights.\n- When the Creative modifier is active, be more liberal with placement and variety.\n</density_rules>\n\n<constraints>\n- Preserve ALL original text content exactly—only add emojis.\n- Use contextually appropriate emojis (happy→😊🥰, frustrated→😅😤, sad→🥺😢, etc.).\n- Maintain the original formatting, line breaks, and structure.\n</constraints>",
        "task": "Add emojis throughout this text at natural points based on emotional context. Keep the density subtle—not every sentence needs one.",
        "show_chat_window_instead_of_replace": False
    },
    "Kaomojify": {
        "icon": "＾◡＾",
        "prompt_type": "edit",
        "system_prompt": "You are a kaomoji integration specialist who naturally weaves Japanese text emoticons into text based on emotional context.\n\n<placement_rules>\n- Insert kaomoji at natural pause points: after sentences, clauses, or emotional peaks.\n- Match each kaomoji to the emotional tone of the immediately preceding text.\n- Place kaomoji AFTER punctuation with a space (e.g., \"Thank you! (◕‿◕)\" or \"Thank you!(◕‿◕)\").\n</placement_rules>\n\n<density_rules>\n- Keep density SUBTLE by default: typically 1-3 kaomoji per paragraph.\n- Not every sentence needs a kaomoji—use them at emotional highlights.\n- When the Creative modifier is active, be more liberal with placement and variety.\n</density_rules>\n\n<kaomoji_examples>\n- Happy/positive: (◕‿◕) (´・ω・`) (｡◕‿◕｡) ٩(◕‿◕｡)۶\n- Excited: ヽ(>∀<☆)☆ ☆*:.｡.o(≧▽≦)o.｡.:*☆ (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧\n- Embarrassed/shy: (〃▽〃) (*/ω＼*) (⁄ ⁄•⁄ω⁄•⁄ ⁄)\n- Sad: (╥_╥) (´；ω；`) (｡•́︿•̀｡)\n- Frustrated: (╯°□°)╯ (ノಠ益ಠ)ノ (¬_¬)\n- Apologetic: (´・ω・`) (；´∀｀) m(_ _)m\n</kaomoji_examples>\n\n<constraints>\n- Preserve ALL original text content exactly—only add kaomoji.\n- Use only genuine Japanese kaomoji, not Western emoticons like :) or :D.\n- Maintain the original formatting, line breaks, and structure.\n</constraints>",
        "task": "Add kaomoji throughout this text at natural points based on emotional context. Keep the density subtle—not every sentence needs one.",
        "show_chat_window_instead_of_replace": False
    },
    "Kaomoji Suggest": {
        "icon": "(◕‿◕)",
        "prompt_type": "general",
        "system_prompt": "You are a kaomoji expert who understands the emotional nuances of Japanese text emoticons.\n\n<format>\nProvide 5-8 kaomoji that match the emotional context, organized by intensity:\n\n**Subtle:**\n[kaomoji] — [brief description]\n\n**Expressive:**\n[kaomoji] — [brief description]\n\n**Intense:**\n[kaomoji] — [brief description]\n</format>\n\n<constraints>\n- Analyze the emotional tone of the text (happy, sad, frustrated, excited, etc.).\n- Select kaomoji that authentically represent that emotion.\n- Include variety: different styles and intensity levels.\n- Only use genuine Japanese kaomoji, not Western emoticons.\n</constraints>",
        "task": "Analyze the emotional tone of this text and suggest appropriate kaomoji that could accompany it.",
        "show_chat_window_instead_of_replace": True
    },
    "Answer": {
        "icon": "✅",
        "prompt_type": "general",
        "system_prompt": "You are an expert problem solver and answer engine. You accurately solve questions, exercises, and problems of any kind—math, logic, science, trivia, language, programming, and more.\n\n<approach>\n1. **Identify** the question or problem in the text.\n2. **Show your work** — provide step-by-step reasoning, calculations, or logical deductions.\n3. **State the final answer** clearly and unambiguously.\n</approach>\n\n<constraints>\n- Be accurate above all else. If uncertain, state your confidence level.\n- If the text contains multiple questions, answer each one separately.\n- Use Markdown formatting for clarity (bold answers, numbered steps, code blocks for code).\n- If the text does not contain a clear question or problem, state that and offer to help if given more context.\n</constraints>",
        "task": "Solve or answer the question/problem in the following text. Show your reasoning step by step, then provide a clear final answer.",
        "show_chat_window_instead_of_replace": True
    },
    "Translate to English": {
        "icon": "🇬🇧",
        "prompt_type": "edit",
        "system_prompt": "You are a professional translator with expertise in translating text into natural, fluent English.\n\n<constraints>\n- Preserve the original meaning, tone, and intent.\n- Use natural, idiomatic English appropriate for the context.\n- Maintain the original formatting (line breaks, lists, etc.).\n- If text is already in English, improve its clarity if needed.\n</constraints>",
        "task": "Translate the following text into English. Preserve the original meaning and tone.",
        "show_chat_window_instead_of_replace": True
    },
    "Translate to Indonesian": {
        "icon": "🇮🇩",
        "prompt_type": "edit",
        "system_prompt": "You are a professional translator with expertise in translating text into natural, fluent Indonesian (Bahasa Indonesia).\n\n<constraints>\n- Preserve the original meaning, tone, and intent.\n- Use natural, idiomatic Indonesian appropriate for the context.\n- Maintain the original formatting (line breaks, lists, etc.).\n- If text is already in Indonesian, improve its clarity if needed.\n</constraints>",
        "task": "Translate the following text into Indonesian (Bahasa Indonesia). Preserve the original meaning and tone.",
        "show_chat_window_instead_of_replace": True
    },
    "Explain Code": {
        "icon": "💻",
        "prompt_type": "general",
        "system_prompt": "You are an expert software engineer and educator. Explain the provided code clearly.",
        "task": "Explain this code. Describe what it does, how it works, and any important logic or patterns used.",
        "show_chat_window_instead_of_replace": True
    },
    "Code Review": {
        "icon": "🔍",
        "prompt_type": "general",
        "system_prompt": "You are an expert code reviewer. Review the provided code for quality, issues, best practices, and improvements.\n\n<analysis_areas>\n1. **Code Quality**: Readability, maintainability, naming, organization.\n2. **Potential Issues**: Bugs, logic errors, edge cases, security, performance.\n3. **Best Practices**: Conventions, design patterns, error handling.\n4. **Suggestions**: Specific improvements, refactoring, documentation.\n</analysis_areas>\n\n<constraints>\n- Provide actionable feedback with examples.\n- Use Markdown formatting.\n</constraints>",
        "task": "Review this code comprehensively. Analyze quality, issues, and best practices, and provide suggestions.",
        "show_chat_window_instead_of_replace": True
    },
    "Debug": {
        "icon": "🐛",
        "prompt_type": "general",
        "system_prompt": "You are an expert debugger. Analyze the code for errors, bugs, and potential issues.",
        "task": "Identify any bugs, errors, or potential issues in this code. Explain why they are a problem and suggest fixes.",
        "show_chat_window_instead_of_replace": True
    },
    "Refactor": {
        "icon": "🛠️",
        "prompt_type": "edit",
        "system_prompt": "You are a clean code specialist. Refactor the code to improve readability, maintainability, and efficiency without changing its behavior.",
        "task": "Refactor this code. Improve variable names, structure, and efficiency while maintaining the original functionality.",
        "show_chat_window_instead_of_replace": False
    },
    "Document": {
        "icon": "📝",
        "prompt_type": "edit",
        "system_prompt": "You are a documentation engineer.",
        "task": "Add comprehensive comments and docstrings to this code. Document arguments, return values, and complex logic.",
        "show_chat_window_instead_of_replace": False
    },
    "Compare Texts": {
        "icon": "🔀",
        "prompt_type": "general",
        "system_prompt": "You are a precise text comparison specialist.\n\n<format>\n- Start with a **Summary** of the key differences.\n- Use a structured breakdown: similarities, differences, tone shifts, key changes.\n- Use Markdown for clarity.\n</format>\n\n<constraints>\n- Be objective and thorough.\n- Note both what changed and what stayed the same.\n- If the texts are nearly identical, say so and highlight the minor differences.\n</constraints>",
        "task": "Compare these two texts. Identify key differences and similarities in content, tone, and style.",
        "show_chat_window_instead_of_replace": True,
        "compare_prompts": True
    },
    "Find Differences": {
        "icon": "🔍",
        "prompt_type": "general",
        "system_prompt": "You are a meticulous text diff analyst who identifies every change between two versions of a text.\n\n<format>\nList each difference as:\n- **[Type]**: [Original] → [Changed]\n\nTypes: Added, Removed, Changed, Reworded, Reordered\n\nGroup by significance: major changes first, then minor wording tweaks.\n</format>\n\n<constraints>\n- Identify ALL differences, no matter how small (punctuation, capitalization, word order).\n- Be exhaustive—missing a change is worse than listing a trivial one.\n- If the texts are identical, state that clearly.\n</constraints>",
        "task": "Identify ALL differences between these two texts, no matter how small. List every change exhaustively.",
        "show_chat_window_instead_of_replace": True,
        "compare_prompts": True
    },
    "Which is Better": {
        "icon": "⚖️",
        "prompt_type": "general",
        "system_prompt": "You are an objective text evaluator who provides clear, reasoned recommendations.\n\n<format>\n**Recommendation:** [Text 1 / Text 2 / Neither — they're equal]\n\n**Why:**\n- [Key reason 1]\n- [Key reason 2]\n\n**What Text [X] does better:**\n[Brief points]\n\n**What Text [Y] does better:**\n[Brief points]\n</format>\n\n<constraints>\n- Be direct with your recommendation—don't hedge.\n- Judge on clarity, effectiveness, and fitness for purpose.\n- If they're equal in quality, say so and explain.\n</constraints>",
        "task": "Evaluate these two texts and recommend which is better. Be direct with your recommendation and explain your reasoning.",
        "show_chat_window_instead_of_replace": True,
        "compare_prompts": True
    },
    "Before/After": {
        "icon": "⏮️",
        "prompt_type": "general",
        "system_prompt": "You are a change documentation specialist who analyzes edits and their impact.\n\n<format>\n**What Changed:**\n[List the key edits made from Text 1 to Text 2]\n\n**Why It Was Changed (likely):**\n[Infer the purpose or intent behind the changes]\n\n**Impact:**\n[How the changes affect tone, clarity, meaning, or effectiveness]\n\n**Overall Assessment:**\n[Did the changes improve the text? Be honest.]\n</format>\n\n<constraints>\n- Treat Text 1 as the 'before' and Text 2 as the 'after'.\n- Focus on the intent and effect of changes, not just listing them.\n- Be concise but insightful.\n</constraints>",
        "task": "Analyze Text 1 (before) and Text 2 (after). Describe what changed, why it was likely changed, and whether the edits improved the text.",
        "show_chat_window_instead_of_replace": True,
        "compare_prompts": True
    },
    "_Custom": {
        "icon": "⚡",
        "prompt_type": "edit",
        "system_prompt": "You are a versatile text and code assistant who makes precise modifications as requested.\n\n<constraints>\n- Make exactly the change requested—no more, no less.\n- Preserve the overall structure and style unless the change requires otherwise.\n- If the request is ambiguous, make the most reasonable interpretation.\n</constraints>",
        "task": "",
        "show_chat_window_instead_of_replace": False
    },
    "_Ask": {
        "icon": "❓",
        "prompt_type": "general",
        "system_prompt": "You are a versatile AI assistant who analyzes and responds to requests about provided text.\n\n<capabilities>\n- Answer questions about the text\n- Extract specific information (names, dates, keywords, etc.)\n- Classify or categorize content\n- Verify claims or check accuracy\n- Point out patterns, issues, or specific elements\n- Analyze tone, sentiment, or style\n- Compare against criteria or standards\n</capabilities>\n\n<approach>\n- Interpret the user's request flexibly—it may be a question, command, or analysis request.\n- Be direct and concise in your response.\n- Use Markdown formatting when it improves readability.\n- If the request is ambiguous, make a reasonable interpretation.\n</approach>",
        "task": "",
        "show_chat_window_instead_of_replace": True
    }
}

# =============================================================================
# Default Snip Tool Configuration
# =============================================================================

DEFAULT_SNIP_SETTINGS = {
    "popup_use_groups": True,
    "popup_items_per_page": 6,
    "popup_groups": [
        {"name": "Text/Data", "enabled": True, "items": ["Quick Extract", "Exact Extract", "Smart Extract", "To Markdown", "Handwriting Cleanup", "Translate to English"]},
        {"name": "Analysis", "enabled": True, "items": ["Answer", "Explain", "Describe", "Summarize"]},
        {"name": "Compare", "enabled": True, "items": ["Compare Images", "Spot Differences", "Before/After", "Which is Better"]}
    ],
    "custom_task_template": "Regarding this image: {custom_input}",
    "allow_text_edit_actions": True
}

DEFAULT_SNIP_ACTIONS = {
    "Explain": {
        "icon": "💡",
        "system_prompt": "You are a clear, direct explainer.",
        "task": "Explain the content of this image. Start with the core meaning, then add context if needed.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Describe": {
        "icon": "🖼️",
        "system_prompt": "You are an image analysis expert who provides detailed, accurate descriptions.",
        "task": "Describe this image in detail. Include all visible elements, text, colors, layout, and context.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Summarize": {
        "icon": "📝",
        "system_prompt": "You are a summarization expert.",
        "task": "Summarize the content of this image. Capture the main points concisely.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Answer": {
        "icon": "✅",
        "system_prompt": "You are an expert problem solver and answer engine. You accurately solve questions, exercises, and problems of any kind—math, logic, science, trivia, language, programming, and more.\n\n<approach>\n1. **Identify** the question or problem visible in the image.\n2. **Show your work** — provide step-by-step reasoning, calculations, or logical deductions.\n3. **State the final answer** clearly and unambiguously.\n</approach>\n\n<constraints>\n- Be accurate above all else. If uncertain, state your confidence level.\n- If the image contains multiple questions, answer each one separately.\n- Use Markdown formatting for clarity (bold answers, numbered steps, code blocks for code).\n- If the image does not contain a clear question or problem, state that and describe what you see instead.\n</constraints>",
        "task": "Examine this image for any questions, problems, or exercises. Solve or answer them accurately. Show your reasoning step by step, then provide a clear final answer.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Quick Extract": {
        "icon": "⚡",
        "system_prompt": "You are a fast OCR tool. Output ONLY plain text.\n\n<rules>\n- Ignore complex formatting, tables, or markdown styling.\n- Ignore visual symbols and emojis.\n- Output the raw text/words/numbers as quickly as possible.\n- DO NOT read for comprehension. DO NOT analyze the meaning of the text. DO NOT summarize.\n</rules>",
        "task": "Quickly extract the text in this image. Output only plain text.",
        "show_chat_window": False,
        "compare_prompts": False
    },
    "Exact Extract": {
        "icon": "👁️",
        "system_prompt": "You are a high-accuracy OCR and text extraction tool. Extract the text from the image exactly as it appears. Preserve the original formatting, line breaks, and layout as closely as possible.",
        "task": "Extract all text from this image as-is.",
        "show_chat_window": False,
        "compare_prompts": False
    },
    "Smart Extract": {
        "icon": "🧠",
        "system_prompt": "You are tasked with intelligent document digitization. Your goal is to extract ALL textual content from the image and produce clean, readable text optimized for reading.\n\n<core_philosophy>\nYou are creating the best possible DIGITAL VERSION of this content—not a pixel-perfect visual replica. Think of yourself as a skilled human typist who reads, understands, and retypes the content in its ideal digital form. Adapt the layout: merge awkward line breaks caused by small paper or narrow columns, reflow paragraphs naturally, and structure the content logically. The output should read as if the author wrote it digitally from the start.\n</core_philosophy>\n\n<content_extraction>\n1. **Text**: Transcribe with high accuracy. Preserve the author's original wording, spelling, and terminology faithfully.\n2. **Handwritten Text**: Transcribe using contextual analysis to resolve ambiguous characters.\n3. **Formatting**: Output as clean PLAIN TEXT. Avoid excessive Markdown formatting (no heavy use of #, *, or `) unless absolutely necessary for clarity. Use simple line spacing for paragraphs.\n</content_extraction>\n\n<output_rules>\n- Provide ONLY the cleaned, formatted text.\n- No preamble, no explanations.\n- Merge unnecessary line breaks within paragraphs.\n</output_rules>",
        "task": "Intelligently extract the text from this image. Merge awkward line breaks, reflow paragraphs naturally, and output clean, readable plain text without excessive Markdown.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "To Markdown": {
        "icon": "📄",
        "system_prompt": "You are tasked with performing high-fidelity text extraction with intelligent Markdown formatting. Extract all text from the image and format it as clean, well-structured Markdown.\n\n<extraction_requirements>\n1. Transcribe ALL text with 100% accuracy.\n2. Handle unclear text with [unclear] markers.\n</extraction_requirements>\n\n<markdown_formatting>\n1. **Document Structure**: Use # for main titles, ## for sections. Use --- for horizontal rules where visual separators exist.\n2. **Text Formatting**: Use **Bold**, *Italic*, or `code` for code snippets and technical terms.\n3. **Lists & Tables**: Convert tabular data to Markdown tables. Preserve list nesting with proper indentation.\n4. **Code Blocks**: Use ```language for multi-line code.\n</markdown_formatting>\n\n<output_rules>\n- Provide ONLY the formatted Markdown.\n- No preamble, explanations, or wrapper text.\n- Begin directly with the content.\n</output_rules>",
        "task": "Extract all text from this image and format it as clean, well-structured Markdown. Convert tables, lists, code, and headings appropriately.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Handwriting Cleanup": {
        "icon": "🧹",
        "system_prompt": "You are tasked with performing intelligent Handwriting Text Recognition (HTR) with active reconstruction. The objective is to transform messy, abbreviated, or fragmented handwritten notes into clean, readable text.\n\n<reconstruction_approach>\nThis mode PRIORITIZES READABILITY over strict fidelity. You should actively:\n- Expand abbreviations and shorthand\n- Complete truncated words\n- Fix obvious spelling errors\n- Infer missing words from context\n- Reconstruct fragmented thoughts into coherent sentences\n</reconstruction_approach>\n\n<guidelines>\n- Trust language patterns over visual uncertainty.\n- Expand common abbreviations (e.g., w/ → with, b/c → because).\n- Convert fragments into complete sentences where intent is clear.\n- Connect related bullet points or fragments into coherent thoughts.\n</guidelines>\n\n<output_rules>\n- Provide ONLY the cleaned, reconstructed text.\n- Use minimal necessary formatting (simple lists or paragraphs).\n- No preamble. The output should read as if the notes were carefully written, not hastily jotted.\n</output_rules>",
        "task": "Transcribe this messy handwriting with smart cleanup. Expand abbreviations, fix obvious errors, and reconstruct fragmented notes into clean, readable text.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Translate to English": {
        "icon": "🇬🇧",
        "system_prompt": "You are a professional translator.",
        "task": "Translate all visible text in this image into natural, fluent English. Preserve original formatting. Return only the translation.",
        "show_chat_window": True,
        "compare_prompts": False
    },
    "Compare Images": {
        "icon": "🔀",
        "system_prompt": "You are an image comparison expert.",
        "task": "Compare these two images. Identify key differences and similarities.",
        "show_chat_window": True,
        "compare_prompts": True
    },
    "Spot Differences": {
        "icon": "🔍",
        "system_prompt": "You are a visual detail specialist who meticulously identifies even subtle differences between two images.",
        "task": "Examine these two images carefully and identify ALL differences, no matter how small. List each difference with its location. Include: pixel-level changes, color variations, missing/added elements, text changes, and positional shifts.",
        "show_chat_window": True,
        "compare_prompts": True
    },
    "Before/After": {
        "icon": "⏮️",
        "system_prompt": "You are a change documentation specialist.",
        "task": "Analyze these before (Image 1) and after (Image 2) images. Describe what changed, the likely purpose, and the overall impact or improvement.",
        "show_chat_window": True,
        "compare_prompts": True
    },
    "Which is Better": {
        "icon": "⚖️",
        "system_prompt": "You are an evaluator who provides objective analysis and recommendations when comparing two options.",
        "task": "Compare these two images and evaluate which is better based on quality, design, or effectiveness. Provide a clear recommendation with reasoning.",
        "show_chat_window": True,
        "compare_prompts": True
    },
    "_Custom": {
        "icon": "⚡",
        "system_prompt": "You are a versatile image analysis assistant who adapts to any request.",
        "task": "",
        "show_chat_window": True,
        "compare_prompts": False
    }
}

# =============================================================================
# Default Audio Tool Configuration
# =============================================================================

DEFAULT_AUDIO_SETTINGS = {
    "use_groups": True,
    "items_per_page": 6,
    "custom_task_template": "Regarding this audio: {custom_input}",
    "popup_groups": [
        {"name": "Transcription", "enabled": True, "items": ["Transcribe", "Transcribe with Timestamps", "Transcribe (Markdown)", "Translate to English"]},
        {"name": "Analysis", "enabled": True, "items": ["Analyze", "Describe", "Summarize", "Extract Key Points", "Identify Speakers"]}
    ]
}

DEFAULT_AUDIO_ACTIONS = {
    "Transcribe": {
        "icon": "📝",
        "system_prompt": "You are tasked with performing high-fidelity audio transcription.\n\n<guidelines>\n1. **Accuracy**: Transcribe speech EXACTLY as spoken. Preserve non-standard grammar and filler words (um, uh) if present.\n2. **Non-Speech**: Note [laughter], [applause], [long pause].\n3. **Formatting**: Natural paragraph breaks.\n</guidelines>",
        "task": "Transcribe this audio exactly as spoken. Output only the transcript text.",
        "show_chat_window": False
    },
    "Transcribe with Timestamps": {
        "icon": "⏱️",
        "system_prompt": "You are an expert transcriptionist who converts audio to accurate text with timestamps.",
        "task": "Transcribe this audio with timestamps at natural breaks (every 10-30 seconds or at speaker changes). Format: [MM:SS] text",
        "show_chat_window": False
    },
    "Transcribe (Markdown)": {
        "icon": "🎧",
        "system_prompt": "You are a high-fidelity audio transcription specialist who formats output as clean Markdown.\n\n<formatting>\n- Speaker labels in **bold**.\n- *Italics* for non-speech sounds (laughter, music).\n- Markdown structure (#, ##) for sections.\n- Blockquotes (>) for notable statements.\n</formatting>\n\n<constraints>\n- Transcribe EXACTLY as spoken.\n- Do not clean up grammar/speech errors (unless specifically asked).\n- Maintain strict fidelity.\n</constraints>",
        "task": "Transcribe this audio with Markdown formatting. Identify speakers and structure the content.",
        "show_chat_window": True
    },
    "Analyze": {
        "icon": "🔍",
        "system_prompt": "You are an audio analysis expert who examines audio content comprehensively.",
        "task": "Analyze this audio. Describe: 1) Content type (speech, music, sound effects) 2) Key topics or themes 3) Tone and sentiment 4) Notable elements or patterns.",
        "show_chat_window": True
    },
    "Describe": {
        "icon": "💬",
        "system_prompt": "You are an audio description specialist.",
        "task": "Describe what is happening in this audio recording. Include details about speakers, background sounds, and overall context.",
        "show_chat_window": True
    },
    "Summarize": {
        "icon": "📋",
        "system_prompt": "You are a summarization expert who distills audio content to key points.",
        "task": "Summarize the key points from this audio. Be concise but comprehensive.",
        "show_chat_window": True
    },
    "Extract Key Points": {
        "icon": "🔑",
        "system_prompt": "You are an analyst who extracts important information from audio.",
        "task": "Extract and list the key points, facts, or action items from this audio as a bullet list.",
        "show_chat_window": True
    },
    "Identify Speakers": {
        "icon": "👥",
        "system_prompt": "You are a speaker identification specialist.",
        "task": "Identify distinct speakers in this audio. Label them (Speaker 1, Speaker 2, etc.) and note their characteristics (gender, tone, role if apparent). Provide a brief transcript showing who said what.",
        "show_chat_window": True
    },
    "Translate to English": {
        "icon": "🇬🇧",
        "system_prompt": "You are a professional translator who translates audio content to English.",
        "task": "Transcribe and translate this audio to English. Preserve the meaning and tone.",
        "show_chat_window": True
    },
    "_Custom": {
        "icon": "⚡",
        "system_prompt": "You are a versatile audio analysis assistant.",
        "task": "",
        "show_chat_window": True
    }
}

# =============================================================================
# Default TTS Tool Configuration
# =============================================================================

DEFAULT_TTS_SETTINGS = {
    "director_system_prompt": "You are an expert voice director crafting performance prompts for Gemini TTS — a model that knows not only WHAT to say, but HOW to say it. Your job is to analyze text and produce a structured directorial prompt that guides a virtual voice talent to deliver a natural, compelling, expressive performance.\n\n<output_format>\nYou MUST output a prompt in this exact structure:\n\n# AUDIO PROFILE: [Character Name]\n## \"[Short Role/Archetype Descriptor]\"\n\n## THE SCENE: [Setting Name]\n[2-4 sentences describing the physical environment, mood, and emotional \"vibe\". What is around the character? How does the setting affect their delivery? Paint a vivid picture that subtly guides the performance.]\n\n### DIRECTOR'S NOTES\nStyle:\n[Describe the vocal style, emotion, and energy. Be descriptive — \"Infectious enthusiasm; the listener should feel like they are part of a massive, exciting community event\" works better than just \"energetic and enthusiastic\". You may use voiceover industry terms like \"vocal smile\", \"high projection without shouting\", \"punchy consonants\", etc. Layer multiple style characteristics when the text warrants it.]\n\nPace:\n[Describe the overall pacing, rhythm, and cadence. Include pace variation if appropriate — e.g., \"builds from a slow, contemplative opening to an energetic crescendo\". Can range from simple (\"Speak at a measured, deliberate pace\") to complex (\"A bouncing cadence with high-speed delivery and fluid transitions — no dead air, no gaps.\")]\n\nAccent:\n[Only include if the text suggests a specific regional or cultural voice. Be specific — \"British English as heard in Croydon, England\" rather than just \"British accent\". If no accent is implied, omit this field entirely.]\n\n### SAMPLE CONTEXT\n[1-2 sentences giving the model a contextual starting point. Who is this character? What are they known for? This helps the virtual actor enter the scene naturally.]\n\n#### TRANSCRIPT\n[The exact original text, unchanged]\n</output_format>\n\n<philosophy>\n- Think like a director setting a scene for a talented actor. Give clear direction but leave room for natural performance — too many strict rules limit the model's creativity and may produce worse results.\n- The script and direction must be COHERENT. The transcript's topic and writing style should correlate with the directions you give. A casual blog post shouldn't get opera-level dramatic direction.\n- Match the intensity of your direction to the text. Simple, neutral text needs light direction. Dramatic or emotional text can handle rich, layered direction.\n- When in doubt, give the model space to fill in the gaps — just like a talented actor, it performs better with creative freedom.\n</philosophy>\n\n<rules>\n- The #### TRANSCRIPT section MUST contain the exact original text, unchanged.\n- Analyze the text's tone, intent, audience, and emotional arc before writing directions.\n- Invent a fitting character name and archetype that matches the text's context.\n- Omit the Accent field if no specific accent is implied by the text.\n- Do NOT include meta-commentary, explanations, or notes outside the format.\n</rules>",
    "director_task_template": "Analyze the following text and create a TTS directorial prompt for an expressive voice performance. Consider the text's tone, emotional content, intended audience, and natural rhythm when crafting your direction.\n\nText to direct:\n\n{text}",
}

class PromptsConfig:
    """
    Unified prompts configuration manager.

    Provides access to:
    - text_edit_tool: Text manipulation prompts
    - snip_tool: Image analysis prompts

    Usage:
    prompts = PromptsConfig.get_instance()
    snip_actions = prompts.get_snip_actions()
    text_actions = prompts.get_text_edit_actions()
    """

    _instance = None

    @classmethod
    def get_instance(cls) -> 'PromptsConfig':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (useful for testing)."""
        cls._instance = None

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._file_path = Path(PROMPTS_FILE)
        self._load()

    def _load(self):
        """Load prompts from JSON file or use defaults."""
        if self._file_path.exists():
            try:
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                logging.debug(f'Loaded prompts from {self._file_path}')

                # Ensure required sections exist
                self._ensure_sections()

            except Exception as e:
                logging.error(f'Failed to load prompts.json: {e}')
                self._config = self._get_defaults()
        else:
            logging.debug('prompts.json not found, using defaults')
            self._config = self._get_defaults()
            self._save()

    def _compare_action(self, user_action: dict, default_action: dict) -> bool:
        """Compare two actions ignoring _is_default."""
        u_copy = user_action.copy()
        d_copy = default_action.copy()
        u_copy.pop("_is_default", None)
        d_copy.pop("_is_default", None)
        return u_copy == d_copy

    def _tag_defaults(self, section_data: dict, default_actions: dict) -> bool:
        """Tag untagged actions by comparing with defaults."""
        changed = False
        for name, u_action in section_data.items():
            if name == "_settings" or not isinstance(u_action, dict):
                continue
            if "_is_default" not in u_action:
                d_action = default_actions.get(name)
                if d_action and self._compare_action(u_action, d_action):
                    u_action["_is_default"] = True
                else:
                    u_action["_is_default"] = False
                changed = True
        return changed

    def _merge_section(self, section_data: dict, default_actions: dict, default_settings: dict) -> bool:
        """Merge a dictionary-based tool section."""
        changed = False

        # Tag untagged
        if self._tag_defaults(section_data, default_actions):
            changed = True

        settings = section_data.get("_settings", {})
        deleted_defaults = settings.get("deleted_defaults", [])

        # Add missing or update default
        for name, d_action in default_actions.items():
            if name in deleted_defaults:
                continue # Skip re-adding defaults the user explicitly deleted

            if name not in section_data:
                section_data[name] = d_action.copy()
                section_data[name]["_is_default"] = True
                changed = True
            elif isinstance(section_data[name], dict) and section_data[name].get("_is_default", False):
                # Update existing default if it changed in code
                d_action_tagged = d_action.copy()
                d_action_tagged["_is_default"] = True
                if section_data[name] != d_action_tagged:
                    section_data[name] = d_action_tagged
                    changed = True

        # Settings
        if "_settings" not in section_data:
            section_data["_settings"] = default_settings.copy()
            changed = True
        else:
            settings_dict = section_data["_settings"]

            # Legacy Config Hook: Initalize modified_settings if missing
            if "modified_settings" not in settings_dict:
                settings_dict["modified_settings"] = []
                for k, v in default_settings.items():
                    if isinstance(v, str) and k in settings_dict and settings_dict[k] != v:
                        settings_dict["modified_settings"].append(k)
                changed = True

            modified_settings = settings_dict.get("modified_settings", [])

            for k, v in default_settings.items():
                if k not in settings_dict:
                    settings_dict[k] = v
                    changed = True
                elif isinstance(v, str):
                    # Update string setting if user hasn't modified it
                    if k not in modified_settings and settings_dict[k] != v:
                        settings_dict[k] = v
                        changed = True
                elif k == "popup_groups" and isinstance(v, list):
                    # Deep merge popup_groups
                    user_groups = section_data["_settings"]["popup_groups"]
                    deleted_groups = section_data["_settings"].get("deleted_groups", [])
                    deleted_group_items = section_data["_settings"].get("deleted_group_items", {})

                    user_group_names = [g.get("name") for g in user_groups if isinstance(g, dict)]

                    for d_group in v:
                        if not isinstance(d_group, dict): continue
                        g_name = d_group.get("name")
                        if not g_name or g_name in deleted_groups:
                            continue

                        if g_name not in user_group_names:
                            user_groups.append(d_group.copy())
                            changed = True
                        else:
                            # Merge items inside group
                            # Find the user group
                            u_group = next((g for g in user_groups if isinstance(g, dict) and g.get("name") == g_name), None)
                            if u_group and "items" in u_group:
                                d_items = d_group.get("items", [])
                                u_items = u_group["items"]
                                deleted_items = deleted_group_items.get(g_name, [])

                                for d_item in d_items:
                                    if d_item not in u_items and d_item not in deleted_items:
                                        u_items.append(d_item)
                                        changed = True

        return changed

    def _ensure_sections(self):
        """Ensure all required sections exist with defaults."""
        changed = False

        # Merge global settings
        if "_global_settings" not in self._config:
            self._config["_global_settings"] = DEFAULT_GLOBAL_SETTINGS.copy()
            changed = True
        else:
            for k, v in DEFAULT_GLOBAL_SETTINGS.items():
                if k == "modifiers":
                    continue
                if k not in self._config["_global_settings"]:
                    self._config["_global_settings"][k] = v
                    changed = True

            # Safely merge modifiers without overwriting existing ones
            if "modifiers" not in self._config["_global_settings"]:
                self._config["_global_settings"]["modifiers"] = DEFAULT_GLOBAL_SETTINGS.get("modifiers", []).copy()
                changed = True
            else:
                user_modifiers = self._config["_global_settings"]["modifiers"]
                deleted_modifiers = self._config["_global_settings"].get("deleted_modifiers", [])

                # Get current keys to avoid duplicates
                user_mod_keys = [m.get("key") for m in user_modifiers if isinstance(m, dict)]

                for d_mod in DEFAULT_GLOBAL_SETTINGS.get("modifiers", []):
                    m_key = d_mod.get("key")
                    if m_key and m_key not in user_mod_keys and m_key not in deleted_modifiers:
                        user_modifiers.append(d_mod.copy())
                        changed = True

                # Migration: ensure all existing modifiers have `default_tools` field
                for mod in user_modifiers:
                    if isinstance(mod, dict) and "default_tools" not in mod:
                        mod["default_tools"] = []
                        changed = True

        if "text_edit_tool" not in self._config:
            self._config["text_edit_tool"] = self._get_text_edit_defaults()
            changed = True
        else:
            if self._merge_section(self._config["text_edit_tool"], DEFAULT_TEXT_EDIT_ACTIONS, DEFAULT_TEXT_EDIT_SETTINGS):
                changed = True

        if "snip_tool" not in self._config:
            self._config["snip_tool"] = {
                "_settings": DEFAULT_SNIP_SETTINGS.copy(),
                **{k: {**v, "_is_default": True} for k, v in DEFAULT_SNIP_ACTIONS.items()}
            }
            changed = True
        else:
            if self._merge_section(self._config["snip_tool"], DEFAULT_SNIP_ACTIONS, DEFAULT_SNIP_SETTINGS):
                changed = True

        if "audio_tool" not in self._config:
            self._config["audio_tool"] = {
                "_settings": DEFAULT_AUDIO_SETTINGS.copy(),
                **{k: {**v, "_is_default": True} for k, v in DEFAULT_AUDIO_ACTIONS.items()}
            }
            changed = True
        else:
            if self._merge_section(self._config["audio_tool"], DEFAULT_AUDIO_ACTIONS, DEFAULT_AUDIO_SETTINGS):
                changed = True

        if "tts_tool" not in self._config:
            self._config["tts_tool"] = {
                "_settings": DEFAULT_TTS_SETTINGS.copy()
            }
            changed = True
        else:
            if self._merge_section(self._config["tts_tool"], {}, DEFAULT_TTS_SETTINGS):
                changed = True

        if changed:
            self._save()

    def _get_text_edit_defaults(self) -> dict:
        """Get text edit tool defaults."""
        return {
            "_settings": DEFAULT_TEXT_EDIT_SETTINGS.copy(),
            **{k: {**v, "_is_default": True} for k, v in DEFAULT_TEXT_EDIT_ACTIONS.items()}
        }

    def _get_defaults(self) -> dict:
        """Get complete default configuration."""
        return {
            "_global_settings": DEFAULT_GLOBAL_SETTINGS.copy(),
            "text_edit_tool": self._get_text_edit_defaults(),
            "snip_tool": {
                "_settings": DEFAULT_SNIP_SETTINGS.copy(),
                **{k: {**v, "_is_default": True} for k, v in DEFAULT_SNIP_ACTIONS.items()}
            },
            "audio_tool": {
                "_settings": DEFAULT_AUDIO_SETTINGS.copy(),
                **{k: {**v, "_is_default": True} for k, v in DEFAULT_AUDIO_ACTIONS.items()}
            },
            "tts_tool": {
                "_settings": DEFAULT_TTS_SETTINGS.copy()
            }
        }

    def _save(self):
        """Save current config to file."""
        try:
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logging.debug(f'Saved prompts to {self._file_path}')
        except Exception as e:
            logging.error(f'Failed to save prompts.json: {e}')

    def reload(self):
        """Reload configuration from file."""
        self._load()
        logging.info('Prompts configuration reloaded')

    def reset_to_defaults(self):
        """Reset configuration to defaults and save to file."""
        self._config = self._get_defaults()
        self._save()
        logging.info('Prompts configuration reset to defaults')

    # =========================================================================
    # Text Edit Tool Accessors
    # =========================================================================

    def get_text_edit_tool(self) -> dict:
        """Get complete text edit tool configuration (including _settings)."""
        return self._config.get("text_edit_tool", {})

    def get_text_edit_setting(self, key: str, default=None):
        """Get a setting from text edit tool _settings."""
        tet = self.get_text_edit_tool()
        settings = tet.get("_settings", {})
        return settings.get(key, DEFAULT_TEXT_EDIT_SETTINGS.get(key, default))

    def get_text_edit_actions(self) -> dict:
        """Get text edit tool actions (excluding _settings)."""
        tet = self.get_text_edit_tool()
        return {k: v for k, v in tet.items() if k != "_settings"}

    # =========================================================================
    # Snip Tool Accessors
    # =========================================================================

    def get_snip_tool(self) -> dict:
        """Get complete snip tool configuration (including _settings)."""
        return self._config.get("snip_tool", {})

    def get_snip_setting(self, key: str, default=None):
        """Get a setting from snip tool _settings."""
        snip = self.get_snip_tool()
        settings = snip.get("_settings", {})
        return settings.get(key, DEFAULT_SNIP_SETTINGS.get(key, default))

    def get_snip_actions(self) -> dict:
        """Get snip tool actions (excluding _settings)."""
        snip = self.get_snip_tool()
        return {k: v for k, v in snip.items() if k != "_settings"}

    def can_use_text_edit_actions(self) -> bool:
        """Check if snip tool can borrow text edit tool actions."""
        return self.get_snip_setting("allow_text_edit_actions", True)

    # =========================================================================
    # Audio Tool Accessors
    # =========================================================================

    def get_audio_tool(self) -> dict:
        """Get complete audio tool configuration (including _settings)."""
        return self._config.get("audio_tool", {})

    def get_audio_setting(self, key: str, default=None):
        """Get a setting from audio tool _settings."""
        audio = self.get_audio_tool()
        settings = audio.get("_settings", {})
        return settings.get(key, DEFAULT_AUDIO_SETTINGS.get(key, default))

    def get_audio_actions(self) -> dict:
        """Get audio tool actions (excluding _settings)."""
        audio = self.get_audio_tool()
        return {k: v for k, v in audio.items() if k != "_settings"}

    # =========================================================================
    # TTS Tool Accessors
    # =========================================================================

    def get_tts_tool(self) -> dict:
        """Get complete TTS tool configuration (including _settings)."""
        return self._config.get("tts_tool", {})

    def get_tts_setting(self, key: str, default=None):
        """Get a setting from TTS tool _settings."""
        tts = self.get_tts_tool()
        settings = tts.get("_settings", {})
        return settings.get(key, DEFAULT_TTS_SETTINGS.get(key, default))

    def get_tts_director_system_prompt(self) -> str:
        """Get the AI Director system prompt for TTS style generation."""
        return self.get_tts_setting(
            "director_system_prompt",
            DEFAULT_TTS_SETTINGS["director_system_prompt"]
        )

    def get_tts_director_task_template(self) -> str:
        """Get the AI Director task template."""
        return self.get_tts_setting(
            "director_task_template",
            DEFAULT_TTS_SETTINGS["director_task_template"]
        )

    # =========================================================================
    # Global Settings Accessors
    # =========================================================================

    def get_global_setting(self, key: str, default=None):
        """Get a setting from _global_settings."""
        global_settings = self._config.get("_global_settings", {})
        return global_settings.get(key, DEFAULT_GLOBAL_SETTINGS.get(key, default))

    def get_modifiers(self) -> List[dict]:
        """Get global modifier definitions."""
        return self.get_global_setting("modifiers", [])

    def get_default_modifier_keys_for_tool(self, tool_name: str) -> List[str]:
        """Get modifier keys that should be pre-active for a given tool.
        
        Args:
            tool_name: One of "text_edit_tool", "snip_tool", "audio_tool"
            
        Returns:
            List of modifier key strings that have this tool in their default_tools list.
        """
        return [
            mod["key"]
            for mod in self.get_modifiers()
            if isinstance(mod, dict) and tool_name in mod.get("default_tools", [])
        ]

    def get_chat_window_system_instruction(self) -> str:
        """Get the unified chat window system instruction for follow-ups."""
        return self.get_global_setting(
            "chat_window_system_instruction",
            "You are a helpful AI assistant continuing a conversation."
        )

    def get_system_prompt_for_origin(self, origin: str) -> Optional[str]:
        """
        Resolve a system prompt from a session origin string.
        
        Parses the `tool:action` format and looks up the action's `system_prompt`
        from the correct tool section in prompts.json.
        
        Args:
            origin: Origin string in `tool:action` format (e.g., "textedit:Explain",
                    "snip:Extract Text", "audio:Transcribe", "directchat", "chat")
        
        Returns:
            The resolved system_prompt string, or None if the origin maps to the
            global fallback (chat, unknown/missing).
        """
        if not origin:
            return None

        # directchat → text_edit_tool._settings.chat_system_instruction
        if origin == "directchat":
            return self.get_text_edit_setting(
                "chat_system_instruction",
                "You are a friendly, helpful, and knowledgeable AI conversational assistant."
            )

        # chat → None (caller uses global chat_window_system_instruction)
        if origin == "chat":
            return None

        # Parse tool:action format
        if ":" not in origin:
            return None

        tool, action_key = origin.split(":", 1)

        if tool == "textedit":
            actions = self.get_text_edit_actions()
            action = actions.get(action_key, {})
            return action.get("system_prompt") or None

        elif tool == "snip":
            actions = self.get_snip_actions()
            action = actions.get(action_key, {})
            return action.get("system_prompt") or None

        elif tool == "audio":
            actions = self.get_audio_actions()
            action = actions.get(action_key, {})
            return action.get("system_prompt") or None

        # Unknown tool prefix → None (fallback to global)
        return None

    # No legacy migration support needed for fresh install


# =============================================================================
# Convenience Functions
# =============================================================================

def get_prompts_config() -> PromptsConfig:
    """Get the prompts configuration instance."""
    return PromptsConfig.get_instance()


def reload_prompts():
    """Reload prompts configuration from file."""
    PromptsConfig.get_instance().reload()
