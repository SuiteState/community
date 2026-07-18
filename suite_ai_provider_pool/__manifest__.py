{
    "name": "AI Provider Pool",
    "summary": "Anthropic Claude, DeepSeek, Ollama, vLLM, LM Studio — add any LLM as a native Odoo 19 AI provider with tool calling, embedding fallback, AI automation model, self-hosted OpenAI-compatible endpoint, one-click model discovery.",
    "description": """
Keywords: AI provider, Claude provider, DeepSeek provider, Ollama Odoo,
vLLM Odoo, LM Studio, self-hosted LLM, OpenAI-compatible, AI agent model,
local LLM, private AI, tool calling, function calling, AI chat provider,
multi-provider AI, custom model, on-premise AI, HuggingFace TGI

AI Provider Pool
================

Registers three additional LLM providers for the native Odoo 19
Enterprise AI app. After installation, the new chat models appear in
the AI Agent model selector alongside OpenAI and Google Gemini.

Providers
---------
- Anthropic Claude (Messages API) with tool calling.
- DeepSeek (Chat Completions API) with function calling.
- Self-Hosted OpenAI-compatible servers (Ollama, vLLM, LM Studio,
  HuggingFace TGI, or any endpoint exposing /v1/chat/completions),
  with function calling. The base URL is configured per database;
  the API key is optional, suitable for local installs without auth.

Configuration
-------------
- API keys configured per database in Settings > AI, or via the
  environment variables ODOO_AI_ANTHROPIC_TOKEN, ODOO_AI_DEEPSEEK_TOKEN,
  and ODOO_AI_SELFHOSTED_TOKEN.
- Self-Hosted server URL is auto-completed: typing host:port is enough,
  the /v1 suffix is added automatically.
- Custom Self-Hosted models can be discovered with one click via the
  Fetch Available Models button (calls /v1/models on the server).
- A Test Connection button verifies reachability before going live.
- Multi-company safe: keys and URLs are stored as system parameters.

Embedding Fallback
------------------
Anthropic, DeepSeek, and self-hosted providers do not offer an
embedding API. When an AI Agent uses one of these chat models and
has Knowledge Sources attached, the module automatically falls back
to an embedding provider that has a configured API key (OpenAI or
Google). The user simply needs one embedding-capable key alongside
their chat key. If neither is configured, a clear error message
directs the user to Settings > AI.

AI Automation Model
-------------------
Native Odoo 19 hardcodes OpenAI GPT-4.1 for all AI-powered server
actions (document sorting, automations, etc.). This module adds a
global "AI Automation Model" setting in Settings > AI, allowing
administrators to use Claude, DeepSeek, or a self-hosted model for
all AI automations.

Limitations
-----------
- File attachments, structured output (JSON schema) and web grounding
  are not supported for the new providers. Use OpenAI or Gemini for
  those capabilities.
- AI Field Fill remains OpenAI-only due to Odoo's use of the
  /responses endpoint, which other providers do not support yet.

License: LGPL-3.
""",
    "version": "19.0.1.3.1",
    "category": "Productivity/AI",
    "license": "LGPL-3",
    "author": "SuiteState",
    "website": "https://suitestate.com",
    "depends": ["ai_app"],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "images": ["static/description/suite_ai_pool_screenshot.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
