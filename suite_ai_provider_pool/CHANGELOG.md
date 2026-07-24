# Changelog

All notable changes to **AI Provider Pool** (`suite_ai_provider_pool`).
This changelog starts at 1.5.0; earlier releases predate it.

## [1.5.0] - 2026-07-24

### Added
- **Web search on any AI Agent.** A new **Search the Web** toggle on the AI
  Agent form grounds answers in live web results for all five providers.
  Odoo 19 ships no such toggle — `web_grounding` is an internal API parameter
  that no standard screen ever turns on. This module adds the toggle and wires
  each provider to the right mechanism:
  - **OpenAI / Gemini** — their built-in web search (previously dormant; nothing
    in stock Odoo enabled it).
  - **Claude** — Anthropic's server-side web search tool (already supported).
  - **DeepSeek / self-hosted** — a Tavily-backed `web_search` tool the model
    can call, run in an internal loop. Requires a Tavily API key; without one,
    the agent simply answers without searching.
  Results are localized to the company's country automatically (OpenAI also
  passes the company city). Search runs are capped (max 5 searches, 5 resume
  rounds) so a customer-facing bot can never loop unbounded.
- **Tavily API key** setting (Settings → AI), also readable from
  `ODOO_AI_TAVILY_TOKEN`. Optional — only DeepSeek and self-hosted models need it.
- **Gemini "search + tools" fallback.** Gemini's API cannot combine web search
  with tools; when an agent has both, the module detects the limitation and
  answers without search instead of failing. (Moved here from the WhatsApp AI
  module so every caller — native Ask AI, WhatsApp, etc. — benefits.)

### Changed
- **DeepSeek models updated to V4.** DeepSeek retired the `deepseek-chat` /
  `deepseek-reasoner` API names; the selector now offers **DeepSeek V4 Pro** and
  **DeepSeek V4 Flash**, the models the current API actually serves.

### Notes
- Web search integrates with the WhatsApp AI module (`suite_whatsapp_ai` ≥ 1.8.0):
  its per-account web-search switch is retired in favor of this per-agent toggle.
  The two modules remain independent — WhatsApp AI reads the toggle only when this
  module is installed.
