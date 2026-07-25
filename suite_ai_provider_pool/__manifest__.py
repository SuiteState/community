{
    "name": "AI Provider Pool",
    "summary": "Anthropic Claude, DeepSeek, Kimi, Qwen, MiniMax, Zhipu GLM, Ollama, vLLM, LM Studio — add any LLM as a native Odoo 19 AI provider with tool calling, web search, embedding fallback, AI automation model, self-hosted or OpenAI-compatible cloud endpoint, one-click model discovery.",
    "description": """
Keywords: AI provider, Claude provider, DeepSeek provider, Kimi, Moonshot,
Qwen, Tongyi Qianwen, DashScope, MiniMax, Zhipu, GLM, Ollama Odoo,
vLLM Odoo, LM Studio, self-hosted LLM, OpenAI-compatible, AI agent model,
local LLM, private AI, tool calling, function calling, web search, Tavily,
multi-provider AI, custom model, on-premise AI, HuggingFace TGI

AI Provider Pool
================

Registers three additional LLM providers for the native Odoo 19
Enterprise AI app. After installation, the new chat models appear in
the AI Agent model selector alongside OpenAI and Google Gemini.

Providers
---------
- Anthropic Claude (Messages API) with tool calling and web search.
- DeepSeek (Chat Completions API) with function calling.
- Custom LLM (the "Custom LLM" slot) — connect ANY OpenAI-compatible
  server or cloud that exposes /v1/chat/completions, with function
  calling. This one slot covers both self-hosted engines (Ollama, vLLM,
  LM Studio, HuggingFace TGI) and OpenAI-compatible cloud providers.
  Point the Server URL at the endpoint, set the API key, add the model
  names. The base URL is configured per database; the key is optional
  for local installs without auth. One OpenAI-compatible endpoint is
  active at a time.

Compatible cloud providers (examples)
-------------------------------------
Any endpoint that speaks the OpenAI Chat Completions format works. A few
mainstream ones and their base URLs:
- Moonshot Kimi — https://api.moonshot.ai/v1 (international) or
  https://api.moonshot.cn/v1 (China) — (kimi-k3, kimi-k2, moonshot-v1-*)
- Alibaba Qwen / Tongyi Qianwen (DashScope compatible mode) —
  https://dashscope.aliyuncs.com/compatible-mode/v1 (qwen-max, qwen-plus,
  qwen-turbo, qwen3-*)
- MiniMax — https://api.minimax.io/v1 (MiniMax-M-series; open weights are
  also self-hostable on vLLM)
- Zhipu GLM — https://open.bigmodel.cn/api/paas/v4 (glm-4.6, glm-4-plus)
The URL's own API-version path (/v1, /paas/v4, /compatible-mode/v1) is
preserved, so providers that do not mount their API under /v1 work too.

Configuration
-------------
- API keys configured per database in Settings > AI, or via the
  environment variables ODOO_AI_ANTHROPIC_TOKEN, ODOO_AI_DEEPSEEK_TOKEN,
  and ODOO_AI_SELFHOSTED_TOKEN.
- Server URL is auto-completed: typing host:port is enough and the /v1
  suffix is added automatically, while a full URL that already carries its
  own version path (…/v1, …/paas/v4) is used as-is.
- Custom LLM models can be discovered with one click via the
  Fetch Available Models button (calls /v1/models on the endpoint).
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

Web Search (any provider)
-------------------------
A "Search the Web" toggle on the AI Agent grounds answers in live web
results. Each provider is wired to the right mechanism: OpenAI and Gemini
use their built-in search; Anthropic Claude uses its server-side web
search tool (version matched to the model — dynamic filtering on Claude
4.6+, basic on older); DeepSeek and self-hosted / OpenAI-compatible models
use a Tavily-backed search tool. Tavily needs an API key (Settings > AI or
ODOO_AI_TAVILY_TOKEN); without one those models simply answer without
searching. Results are localized to the company's country, and search runs
are capped so a customer-facing bot can never loop unbounded.

AI Automation Model
-------------------
Native Odoo 19 hardcodes OpenAI GPT-4.1 for all AI-powered server
actions (document sorting, automations, etc.). This module adds a
global "AI Automation Model" setting in Settings > AI, allowing
administrators to use Claude, DeepSeek, or a self-hosted model for
all AI automations.

Limitations
-----------
- File attachments and structured output (JSON schema) are not
  supported for the new providers. Use OpenAI or Gemini for those.
- Web search on DeepSeek and self-hosted / OpenAI-compatible models
  needs a Tavily API key (OpenAI, Gemini and Claude search natively).
- Only one OpenAI-compatible endpoint (the "Custom LLM" slot) can be
  active at a time; connect Kimi or Qwen or MiniMax or GLM, not several
  at once.
- AI Field Fill remains OpenAI-only due to Odoo's use of the
  /responses endpoint, which other providers do not support yet.

License: LGPL-3.
""",
    "version": "19.0.1.5.3",
    "category": "Productivity/AI",
    "license": "LGPL-3",
    "author": "SuiteState",
    "support": "hello@suitestate.com",
    "website": "https://suitestate.com",
    "depends": ["ai_app"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/ai_agent_views.xml",
    ],
    "images": ["static/description/suite_ai_pool_screenshot.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
