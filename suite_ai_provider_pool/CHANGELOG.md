# Changelog

All notable changes to **AI Provider Pool** (`suite_ai_provider_pool`).
This changelog starts at 1.5.0; earlier releases predate it.

## [1.5.4] - 2026-08-31

### Fixed
- **Registry crash under a newer Odoo 19 point release.** Odoo added a required
  field (`response_style_to_llm_model_and_reasoning`) to the `Provider`
  NamedTuple. The provider registration built `Provider(...)` with a fixed
  argument list, so the missing field raised `TypeError` at import — which
  aborts module loading and takes the whole database registry down (500 on
  boot). The three providers now pass the field explicitly.

### Changed
- **Provider registration is now resilient to upstream field changes.**
  Providers are built through a `_make_provider(...)` factory that fills any
  Provider field the running Odoo declares but we did not pass (an upstream
  *addition*) with a type-appropriate empty value, and drops kwargs that are no
  longer fields (an upstream *removal*) — each with a logged `WARNING`. A future
  required-field addition can no longer crash the registry; the module boots and
  flags the change for review instead. Safe because our transport reads only
  name/display_name/embedding_model/llms/deprecated_models; all other Provider
  fields are consumed by upstream's own guarded, provider-specific paths.

## [1.5.3] - 2026-07-25

### Changed
- **Renamed the "Self-Hosted" provider to "Custom LLM" across the UI.**
  The slot has always accepted any OpenAI-compatible endpoint — local or
  cloud — but the "Self-Hosted" label implied it only worked with a model
  running on your own server. The provider (dropdown group, Settings block)
  now reads **Custom LLM**, and its three fields are renamed for clarity:
  **LLM Server URL**, **LLM API Key** and **LLM Models**. All three describe
  the same single endpoint; the field help and the Apps page now spell out
  that self-hosted vs cloud differs only in what you type (URL, whether a key
  is needed), not which fields you use. This touches only display text. The
  stored parameters (`ai.selfhosted_url`, `ai.selfhosted_key`,
  `ai.selfhosted_models`) and the `ODOO_AI_SELFHOSTED_TOKEN` environment
  variable are unchanged, so existing configurations keep working with no
  migration.
- **Docs: added Moonshot Kimi K3 as an example model** (`kimi-k3`, released
  2026-07-16) and listed both Moonshot base URLs — `https://api.moonshot.ai/v1`
  (international) and `https://api.moonshot.cn/v1` (China). No code change:
  K3 is OpenAI-compatible and already reachable through the Custom LLM slot.

## [1.5.2] - 2026-07-25

### Fixed
- **OpenAI-compatible endpoints that don't mount their API under `/v1` now
  work.** The Self-Hosted URL normaliser force-appended `/v1`, which broke
  providers whose API lives under a different version path — notably Zhipu
  GLM (`…/api/paas/v4`). The URL's own version segment (`/v1`, `/v4`,
  `/compatible-mode/v1`) is now preserved; a bare `host:port` still gets
  `/v1` appended as before.

### Changed
- **Docs: the "Self-Hosted" slot is documented as a general
  OpenAI-compatible connector.** It has always accepted any
  `/v1/chat/completions` endpoint; the manifest, Settings help and Apps
  page now spell out the mainstream clouds it reaches — Moonshot Kimi,
  Alibaba Qwen (Tongyi Qianwen / DashScope), MiniMax and Zhipu GLM — with
  their base URLs, alongside the local engines (Ollama, vLLM, LM Studio).
  One OpenAI-compatible endpoint is active at a time.
- **Docs: corrected the web-search description.** The manifest still
  described web search as Anthropic-only; it now reflects the 1.5.0
  reality — a per-agent toggle where OpenAI, Gemini and Claude search
  natively and DeepSeek / self-hosted use Tavily.

## [1.5.1] - 2026-07-24

### Fixed
- **DeepSeek requests no longer time out at 30 s.** DeepSeek chat calls
  inherited Odoo's 30-second default while the Anthropic and self-hosted
  paths already used 120 s; long DeepSeek (reasoner / V4) completions could
  raise a spurious timeout error. DeepSeek now uses the same 120 s budget.

### Changed
- Unified the **AI Automation Model** help text so the field tooltip and the
  Settings description read identically (previously two slightly different
  wordings).

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
