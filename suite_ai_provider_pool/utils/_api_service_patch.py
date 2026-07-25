"""Monkey-patch ``LLMApiService`` to support Anthropic Claude, DeepSeek,
and Self-Hosted (OpenAI-compatible) providers.

Mirrors the contract used by the OpenAI and Google branches in
``odoo.addons.ai.utils.llm_api_service``:

- ``__init__(env, provider)`` sets ``self.provider``, ``self.base_url``,
  ``self.env``. Patched to recognise our three providers; for Self-Hosted
  the base URL is resolved from ``ir.config_parameter`` at call time.
- ``_get_api_token`` reads ``ir.config_parameter`` first, env var as
  fallback. Patched to extend the provider table; the Self-Hosted key
  is optional (returns empty string when unset, suitable for local
  Ollama / vLLM with no auth).
- ``_request_llm`` dispatches by provider after a deprecation check.
  Patched to add anthropic / deepseek / selfhosted branches.
- ``_request_llm_<provider>`` returns ``(response, to_call, next_inputs)``
  where ``response`` is a list of strings, ``to_call`` is a list of
  ``(tool_name, call_id, arguments_dict)`` tuples, and ``next_inputs``
  is the running list of provider-specific message records to feed
  into the next turn.
- ``_build_tool_call_response(tool_call_id, return_value)`` builds the
  message that wraps a tool result for the next turn.

Scope: chat + tool use for all three providers. Web search (``web_grounding``)
is supported on every provider: Anthropic via Claude's server-side web search
tool; DeepSeek and Self-Hosted via a Tavily-backed ``web_search`` function tool
run in an internal loop here (silently skipped when no Tavily key is set). The
``files`` and ``schema`` parameters still raise ``UserError`` for our providers
(out of scope).

This module also owns two cross-provider web-search behaviours so callers
(native Ask AI, WhatsApp AI, …) don't each re-implement them:

- ``request_llm`` is patched so an agent-level opt-in flag carried in the
  context (``ai_web_grounding``, set by ``ai.agent._generate_response``) turns
  on grounding when the caller didn't pass it explicitly. Priority is
  ``explicit web_grounding OR context`` — an explicit truthy value always wins
  and is never overwritten.
- The Gemini "cannot combine web search with tools" ``NotImplementedError`` is
  caught in the dispatcher and retried once without grounding, so every caller
  degrades gracefully instead of dropping the reply.
"""

import json
import logging
import os
import re

import requests

from odoo import _
from odoo.exceptions import UserError
from odoo.addons.ai.utils.ai_logging import api_call_logging
from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils.llm_providers import (
    check_model_depreciation,
    get_provider_for_embedding_model,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider tables
# ---------------------------------------------------------------------------

_BASE_URLS = {
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}

_PROVIDER_CONFIG = {
    "anthropic": {
        "config_key": "ai.anthropic_key",
        "env_var": "ODOO_AI_ANTHROPIC_TOKEN",
    },
    "deepseek": {
        "config_key": "ai.deepseek_key",
        "env_var": "ODOO_AI_DEEPSEEK_TOKEN",
    },
    "selfhosted": {
        "config_key": "ai.selfhosted_key",
        "env_var": "ODOO_AI_SELFHOSTED_TOKEN",
        "optional": True,
    },
}

_SELFHOSTED_URL_PARAM = "ai.selfhosted_url"

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096

# Claude's server-side web search tool. The 20260209 version adds "dynamic
# filtering" and runs on the Claude 4.6+ families (Opus 4.6/4.7/4.8, Sonnet
# 4.6, Fable/Mythos 5); 20250305 is the basic version, which every web-search-
# capable Claude accepts (including the newer ones). We default to basic and
# opt into the newer version only for models known to support it, so an
# unrecognised or future model never 400s — it just misses dynamic filtering.
_WEB_SEARCH_TOOL_NEW = "web_search_20260209"
_WEB_SEARCH_TOOL_BASIC = "web_search_20250305"
# Bound how many searches Claude may run per reply, and how many times we resume
# a paused server-tool turn — both cap cost/latency on a customer-facing bot.
_WEB_SEARCH_MAX_USES = 5
_WEB_SEARCH_MAX_CONTINUATIONS = 5
_CLAUDE_MAJOR_MINOR_RE = re.compile(r"(\d+)-(\d+)")

# Sampling parameters that newer Anthropic models (Opus 4.7+, Fable 5) reject
# with a 400. We send temperature by default; if the API refuses it we strip
# these and retry once. Model-agnostic on purpose (keyed on the API's own 400,
# not a hardcoded model list) so future models are handled without changes.
_SAMPLING_KEYS = ("temperature", "top_p", "top_k")

# Tavily web search, used to ground DeepSeek / Self-Hosted (neither has a
# built-in search tool). We expose a `web_search` function tool to the model
# and run the searches ourselves in an internal loop — same shape as Claude's
# server-side loop, but client-side. Caps mirror the Anthropic path so a
# customer-facing bot can never spin unbounded: at most _MAX_CONTINUATIONS
# resume rounds, and _MAX_USES searches per reply.
_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_KEY_PARAM = "ai.tavily_key"
_TAVILY_ENV_VAR = "ODOO_AI_TAVILY_TOKEN"
_TAVILY_TOOL_NAME = "web_search"
_TAVILY_MAX_RESULTS = 5
_TAVILY_TIMEOUT = 30
# Reuse the same ceilings as the Claude web-search loop for consistency.
_WEB_SEARCH_MAX_USES_TAVILY = _WEB_SEARCH_MAX_USES
_WEB_SEARCH_MAX_CONTINUATIONS_TAVILY = _WEB_SEARCH_MAX_CONTINUATIONS


# A trailing API-version path segment: /v1, /v4, /v1beta… Providers mount their
# OpenAI-compatible API under different versions — Moonshot/DashScope/MiniMax use
# /v1, Zhipu GLM uses /api/paas/v4 — so we must only auto-append /v1 when the URL
# carries no version segment of its own (a bare host:port for local Ollama/vLLM).
_API_VERSION_SEGMENT_RE = re.compile(r"/v\d+[a-z]*$", re.IGNORECASE)


def normalize_selfhosted_url(raw):
    """Best-effort normalization of a user-entered server URL: strip
    whitespace and trailing slash, prepend ``http://`` when no scheme is
    given, and append ``/v1`` only when the URL has no API-version path
    segment yet (so ``…/v4`` or ``…/compatible-mode/v1`` is left intact).
    Returns an empty string if ``raw`` is falsy."""
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    if not _API_VERSION_SEGMENT_RE.search(raw):
        raw = raw + "/v1"
    return raw


def _resolve_selfhosted_base_url(env):
    """Resolve the Self-Hosted base URL from saved settings. Raises a
    user-facing error when the URL is not configured."""
    raw = env["ir.config_parameter"].sudo().get_param(_SELFHOSTED_URL_PARAM, "")
    base_url = normalize_selfhosted_url(raw)
    if not base_url:
        raise UserError(_(
            "Custom LLM server URL is not configured. "
            "Open Settings → AI and fill in the Server URL."
        ))
    return base_url


def selfhosted_request_headers(api_token):
    """Build the headers for a Self-Hosted OpenAI-compatible call.
    Authorization is omitted entirely when no token is configured, so
    local Ollama instances without auth are not tripped by an empty
    Bearer token."""
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def _reject_unsupported(provider, files, schema):
    """Reject the parameters our providers genuinely cannot serve. Web search
    is NOT rejected here: Anthropic handles it via Claude's server tool, and
    DeepSeek / Self-Hosted via the Tavily loop (or a silent skip if unkeyed)."""
    if files:
        raise UserError(_(
            "Provider '%s' does not support file attachments in this module. "
            "Use OpenAI or Gemini for chats that include files.",
            provider,
        ))
    if schema:
        raise UserError(_(
            "Provider '%s' does not support structured output (json schema) "
            "in this module. Use OpenAI or Gemini for structured tasks.",
            provider,
        ))


# ---------------------------------------------------------------------------
# __init__ — extend base_url table
# ---------------------------------------------------------------------------

_orig_init = LLMApiService.__init__


def _patched_init(self, env, provider="openai"):
    if provider in _BASE_URLS:
        self.provider = provider
        self.base_url = _BASE_URLS[provider]
        self.env = env
        return
    if provider == "selfhosted":
        self.provider = provider
        self.env = env
        self.base_url = _resolve_selfhosted_base_url(env)
        return
    _orig_init(self, env, provider)


LLMApiService.__init__ = _patched_init


# ---------------------------------------------------------------------------
# _get_api_token — extend provider_config table
# ---------------------------------------------------------------------------

_orig_get_api_token = LLMApiService._get_api_token


def _patched_get_api_token(self):
    cfg = _PROVIDER_CONFIG.get(self.provider)
    if cfg is None:
        return _orig_get_api_token(self)
    api_key = (
        self.env["ir.config_parameter"].sudo().get_param(cfg["config_key"])
        or os.getenv(cfg["env_var"])
    )
    if api_key:
        return api_key
    if cfg.get("optional"):
        return ""
    raise UserError(_("No API key set for provider '%s'", self.provider))


LLMApiService._get_api_token = _patched_get_api_token


# ---------------------------------------------------------------------------
# get_embedding — reroute chat-only providers to a real embedding provider
# ---------------------------------------------------------------------------
#
# Our three providers (anthropic / deepseek / selfhosted) are chat-only: none
# exposes an /embeddings endpoint (Anthropic returns 404; DeepSeek and a
# typical self-hosted chat server do not implement it). When an AI Agent uses
# one of them for chat but has Knowledge Sources, ai.agent._get_embedding_model
# already falls back to a real embedding model (OpenAI/Google). But native
# _build_rag_context still builds LLMApiService(provider=<chat provider>) and
# calls get_embedding on it, so at query time the request is sent to the chat
# provider's base URL and 404s — RAG silently degrades. (Native's *ingestion*
# path is fine: it derives the provider from the embedding model. Only the
# query path hardcodes the chat provider.)
#
# Fix: when get_embedding runs on one of our chat-only services, derive the
# real provider from the embedding model and send the request there instead.
# No extra configuration needed beyond the OpenAI/Google key the fallback
# already requires.

_orig_get_embedding = LLMApiService.get_embedding


def _patched_get_embedding(self, input, dimensions, model="text-embedding-3-small", *args, **kwargs):
    if self.provider in _BASE_URLS or self.provider == "selfhosted":
        emb_provider = get_provider_for_embedding_model(self.env, model)
        if emb_provider != self.provider:
            return LLMApiService(self.env, emb_provider).get_embedding(
                input, dimensions, model, *args, **kwargs,
            )
    return _orig_get_embedding(self, input, dimensions, model, *args, **kwargs)


LLMApiService.get_embedding = _patched_get_embedding


# ---------------------------------------------------------------------------
# _request_llm — dispatcher extension (deprecation check kept at top)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# request_llm (public) — honour the agent-level web-search opt-in carried in
# the context. Native ``ai.agent._generate_response`` never passes
# web_grounding; our ai.agent override flags it via ``ai_web_grounding`` in the
# context instead of rewriting the native method body. Priority is
# ``explicit OR context`` — an explicitly passed truthy value always wins and a
# caller that passes False on an env WITHOUT the flag stays False, so the
# WhatsApp path (explicit getattr) and native path never fight each other.
# ---------------------------------------------------------------------------

_orig_request_llm_public = LLMApiService.request_llm


def _patched_request_llm_public(self, *args, **kwargs):
    ctx_grounding = bool(self.env.context.get("ai_web_grounding"))
    if ctx_grounding:
        kwargs["web_grounding"] = bool(kwargs.get("web_grounding")) or ctx_grounding
    return _orig_request_llm_public(self, *args, **kwargs)


LLMApiService.request_llm = _patched_request_llm_public


# ---------------------------------------------------------------------------
# _request_llm — dispatcher extension (deprecation check kept at top)
# ---------------------------------------------------------------------------

_orig_request_llm = LLMApiService._request_llm

# Gemini raises this exact message when asked to combine web search with tools
# (native llm_api_service, ~line 439). We match on the message — never a bare
# ``except NotImplementedError`` — so the sibling "structured output with tools"
# error and any future unrelated NotImplementedError still propagate.
_GEMINI_GROUNDING_CONFLICT = "web grounding"


def _patched_request_llm(self, *args, **kwargs):
    if self.provider in ("anthropic", "deepseek", "selfhosted"):
        model = kwargs.get("llm_model") or args[0]
        check_model_depreciation(self.env, model)
        if self.provider == "anthropic":
            return self._request_llm_anthropic(*args, **kwargs)
        if self.provider == "deepseek":
            return self._request_llm_deepseek(*args, **kwargs)
        return self._request_llm_selfhosted(*args, **kwargs)
    # Native providers (openai / google). Gemini can't combine web search with
    # tools; rather than drop the reply, retry once WITHOUT grounding so the
    # customer still gets an answer. Narrowly matched so we never mask an
    # unrelated failure that happens to reuse NotImplementedError.
    try:
        return _orig_request_llm(self, *args, **kwargs)
    except NotImplementedError as exc:
        if kwargs.get("web_grounding") and _GEMINI_GROUNDING_CONFLICT in str(exc).lower():
            _logger.info(
                "%s: web search cannot combine with tools; retrying without it",
                self.provider,
            )
            return _orig_request_llm(self, *args, **{**kwargs, "web_grounding": False})
        raise


LLMApiService._request_llm = _patched_request_llm


# ---------------------------------------------------------------------------
# Anthropic — Messages API
# ---------------------------------------------------------------------------

def _anthropic_tool_schema(tools):
    """Convert internal tool dict to Anthropic's tool schema list."""
    return [
        {
            "name": tool_name,
            "description": tool_description or "",
            "input_schema": tool_parameter_schema or {"type": "object", "properties": {}},
        }
        for tool_name, (tool_description, __, __, tool_parameter_schema) in tools.items()
    ]


def _is_claude_46_plus(model):
    """True for Claude families that support the 20260209 web search tool
    (Opus/Sonnet 4.6+, and the Fable/Mythos 5 line). Unknown models -> False,
    so they fall back to the universally accepted basic tool."""
    if "fable" in model or "mythos" in model:
        return True
    match = _CLAUDE_MAJOR_MINOR_RE.search(model)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (4, 6)


def _anthropic_web_search_tool(llm_model):
    """Claude's server-side web search tool definition, version-matched to the
    model. Runs entirely on Anthropic's side: Claude issues the searches and
    consumes the results itself, so no ``tool_use`` comes back to us to
    execute."""
    version = (
        _WEB_SEARCH_TOOL_NEW
        if _is_claude_46_plus((llm_model or "").lower())
        else _WEB_SEARCH_TOOL_BASIC
    )
    return {"type": version, "name": "web_search", "max_uses": _WEB_SEARCH_MAX_USES}


def _log_anthropic_web_search_error(block):
    """A ``web_search_tool_result`` block carries a list on success or an error
    object on failure (HTTP stays 200). Claude then answers from its own
    knowledge, so we only log the failure for observability."""
    content = block.get("content")
    if isinstance(content, dict) and content.get("type") == "web_search_tool_result_error":
        _logger.info("Anthropic web search error: %s", content.get("error_code"))


def _normalize_anthropic_messages(messages):
    """Merge consecutive ``user`` messages whose content is a list of
    blocks into a single message. Anthropic Messages API requires strict
    user/assistant alternation; the framework's loop produces one user
    message per tool result, so multi-tool turns must be coalesced.
    """
    out = []
    for msg in messages:
        same_role_block_msg = (
            out
            and msg.get("role") == "user"
            and out[-1].get("role") == "user"
            and isinstance(out[-1].get("content"), list)
            and isinstance(msg.get("content"), list)
        )
        if same_role_block_msg:
            out[-1]["content"].extend(msg["content"])
        else:
            content = msg.get("content")
            if isinstance(content, list):
                content = list(content)
            out.append({**msg, "content": content})
    return out


def _request_llm_anthropic(
    self, llm_model, system_prompts, user_prompts, tools=None,
    files=None, schema=None, temperature=0.2, inputs=(), web_grounding=False,
):
    """Anthropic Messages API. Returns ``(response, to_call, next_inputs)``."""
    # web_grounding is handled below (Claude web search tool), so it is not
    # rejected here — only files / schema remain out of scope for Anthropic.
    _reject_unsupported("anthropic", files, schema)

    system_text = "\n\n".join(p for p in (system_prompts or []) if p)
    user_text = "\n\n".join(p for p in (user_prompts or []) if p)

    messages = []
    if user_text:
        messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
    messages.extend(inputs or ())
    messages = _normalize_anthropic_messages(messages)

    body = {
        "model": llm_model,
        "max_tokens": _DEFAULT_MAX_TOKENS,
        "messages": messages,
        "temperature": temperature,
    }
    if system_text:
        body["system"] = system_text
    tool_list = _anthropic_tool_schema(tools) if tools else []
    if web_grounding:
        tool_list.append(_anthropic_web_search_tool(llm_model))
    if tool_list:
        body["tools"] = tool_list

    with api_call_logging(messages, tools) as record_response:
        response, to_call, next_inputs, request_token_usage = self._request_llm_anthropic_helper(body, inputs)
        if record_response:
            record_response(to_call, response, request_token_usage)
        return response, to_call, next_inputs


def _post_anthropic(self, body):
    """POST to /messages, transparently stripping sampling params on refusal.

    Newer Anthropic models (Opus 4.7+, Fable 5) reject temperature/top_p/top_k
    with a 400. On such a 400 we drop those keys and retry once, so the same
    transport works for models that accept sampling params (Sonnet/Haiku, older
    Opus) and those that don't — without a per-model branch. Returns the
    ``requests`` response; raising for status is left to the caller."""
    headers = {
        "x-api-key": self._get_api_token(),
        "anthropic-version": _ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{self.base_url}/messages", headers=headers, json=body, timeout=120,
    )
    if resp.status_code == 400 and any(k in body for k in _SAMPLING_KEYS):
        try:
            message = resp.json().get("error", {}).get("message") or ""
        except ValueError:
            message = resp.text or ""
        if any(k in message for k in _SAMPLING_KEYS):
            body = {k: v for k, v in body.items() if k not in _SAMPLING_KEYS}
            resp = requests.post(
                f"{self.base_url}/messages", headers=headers, json=body, timeout=120,
            )
    return resp


def _request_llm_anthropic_helper(self, body, inputs=()):
    response = []
    to_call = []
    next_inputs = list(inputs or ())
    request_token_usage = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}
    # Base message list, kept intact so each pause_turn resume resends it with a
    # single, growing assistant turn appended (see below).
    base_messages = list(body.get("messages") or ())
    # A server tool (web search) can span several API calls via ``pause_turn``.
    # We stitch every segment's blocks into ONE assistant turn: it is what we
    # resend to resume, and — crucially — the single assistant message we hand
    # back in next_inputs, so a later framework turn never sees two assistant
    # messages in a row (which Anthropic rejects for breaking alternation).
    assistant_blocks = []

    for _attempt in range(_WEB_SEARCH_MAX_CONTINUATIONS + 1):
        body = {**body, "messages": base_messages + (
            [{"role": "assistant", "content": assistant_blocks}] if assistant_blocks else []
        )}
        try:
            resp = self._post_anthropic(body)
            resp.raise_for_status()
        except requests.RequestException as exc:
            error = repr(exc)
            if exc.response is not None:
                try:
                    error = exc.response.json().get("error", {}).get("message") or exc.response.text
                except ValueError:
                    error = exc.response.text
            _logger.warning("Anthropic API request failed: %s", error)
            raise UserError(error)

        data = resp.json()
        content_blocks = data.get("content") or []
        assistant_blocks.extend(content_blocks)

        if usage := data.get("usage"):
            request_token_usage["input_tokens"] += usage.get("input_tokens", 0)
            request_token_usage["cached_tokens"] += (
                usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            request_token_usage["output_tokens"] += usage.get("output_tokens", 0)

        # Server tool hit its internal iteration cap: loop to resume. No extra
        # "Continue" user message — the trailing server_tool_use block signals it.
        if data.get("stop_reason") == "pause_turn" and content_blocks:
            continue
        break
    else:
        _logger.warning(
            "Anthropic web search did not settle after %s continuations; "
            "returning the partial response.", _WEB_SEARCH_MAX_CONTINUATIONS,
        )

    has_tool_use = any(b.get("type") == "tool_use" for b in assistant_blocks)
    for block in assistant_blocks:
        btype = block.get("type")
        if btype == "tool_use":
            to_call.append((block.get("name"), block.get("id"), block.get("input") or {}))
        elif btype == "text" and not has_tool_use:
            if text := block.get("text"):
                response.append(text)
        elif btype == "web_search_tool_result":
            _log_anthropic_web_search_error(block)

    if assistant_blocks:
        next_inputs.append({"role": "assistant", "content": assistant_blocks})

    return response, to_call, next_inputs, request_token_usage


LLMApiService._post_anthropic = _post_anthropic
LLMApiService._request_llm_anthropic = _request_llm_anthropic
LLMApiService._request_llm_anthropic_helper = _request_llm_anthropic_helper


# ---------------------------------------------------------------------------
# OpenAI-compatible (DeepSeek + Self-Hosted) — shared building blocks
# ---------------------------------------------------------------------------

def _openai_compatible_tool_schema(tools):
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description or "",
                "parameters": tool_parameter_schema or {"type": "object", "properties": {}},
            },
        }
        for tool_name, (tool_description, __, __, tool_parameter_schema) in tools.items()
    ]


def _openai_compatible_messages(system_prompts, user_prompts, inputs):
    messages = []
    for sp in system_prompts or ():
        if sp:
            messages.append({"role": "system", "content": sp})
    user_text = "\n\n".join(p for p in (user_prompts or []) if p)
    if user_text:
        messages.append({"role": "user", "content": user_text})
    messages.extend(inputs or ())
    return messages


def _openai_compatible_body(llm_model, messages, temperature, tools):
    body = {
        "model": llm_model,
        "messages": messages,
        "max_tokens": _DEFAULT_MAX_TOKENS,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = _openai_compatible_tool_schema(tools)
        body["tool_choice"] = "auto"
    return body


def _parse_openai_compatible_response(data, inputs, provider_label):
    """Parse an OpenAI-format Chat Completions response into the
    ``(response, to_call, next_inputs, request_token_usage)`` tuple
    expected by the framework. ``provider_label`` is used only for the
    log message when tool-call arguments fail to decode."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    response = []
    to_call = []
    next_inputs = list(inputs or ())

    has_tool_calls = bool(message.get("tool_calls"))

    if has_tool_calls:
        for tc in message["tool_calls"]:
            fn = tc.get("function") or {}
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                _logger.error("AI: Malformed arguments from %s: %s", provider_label, fn)
                continue
            to_call.append((fn.get("name"), tc.get("id"), arguments))
    elif content := message.get("content"):
        response.append(content)

    if message:
        next_inputs.append(message)

    request_token_usage = {}
    if usage := data.get("usage"):
        request_token_usage["input_tokens"] = usage.get("prompt_tokens", 0)
        request_token_usage["cached_tokens"] = usage.get("prompt_cache_hit_tokens", 0)
        request_token_usage["output_tokens"] = usage.get("completion_tokens", 0)

    return response, to_call, next_inputs, request_token_usage


# ---------------------------------------------------------------------------
# Tavily web search — grounds DeepSeek / Self-Hosted, which have no native
# search. We advertise a `web_search` function tool, let the model call it, run
# Tavily ourselves, feed results back, and loop — all transparent to the
# framework's own tool loop (it never sees the web_search tool).
# ---------------------------------------------------------------------------

def _tavily_key(env):
    """Tavily API key from settings, env var as fallback; '' when unset."""
    return (
        env["ir.config_parameter"].sudo().get_param(_TAVILY_KEY_PARAM)
        or os.getenv(_TAVILY_ENV_VAR)
        or ""
    )


def _tavily_tool_def():
    """OpenAI-format function tool the model calls to request a web search."""
    return {
        "type": "function",
        "function": {
            "name": _TAVILY_TOOL_NAME,
            "description": (
                "Search the public web for current, real-time or external "
                "information you are not sure about (news, prices, recent "
                "events, facts that may have changed). Returns a short list of "
                "result snippets with sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, in natural language.",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _format_tavily_results(data):
    """Flatten a Tavily response into a compact text block for the model."""
    parts = []
    if answer := data.get("answer"):
        parts.append("Summary: %s" % answer)
    for r in data.get("results") or ():
        title = r.get("title") or ""
        url = r.get("url") or ""
        content = (r.get("content") or "").strip()
        parts.append("- %s (%s)\n  %s" % (title, url, content))
    return "\n".join(parts) or "No results found."


def _run_tavily_search(env, query):
    """Run one Tavily search. Localizes to the company country (parity with
    OpenAI's native ``user_location``); if the API rejects the ``country``
    param it retries once without it. Returns a text block, or ``None`` when
    no key is set. Any transport error is swallowed to a short notice so the
    model still answers."""
    key = _tavily_key(env)
    if not key:
        return None
    if not (query or "").strip():
        return "No results found."
    payload = {
        "api_key": key,
        "query": query,
        "max_results": _TAVILY_MAX_RESULTS,
        "search_depth": "basic",
        "include_answer": True,
    }
    country = env.company.country_id
    if country and country.name:
        # Tavily's `country` boosts local results; it expects a lowercase
        # country name (e.g. "united arab emirates").
        payload["country"] = country.name.lower()
    for attempt in (1, 2):
        try:
            resp = requests.post(_TAVILY_URL, json=payload, timeout=_TAVILY_TIMEOUT)
            resp.raise_for_status()
            return _format_tavily_results(resp.json())
        except requests.RequestException as exc:
            # First failure with a country hint: it may be an unsupported
            # param on the caller's Tavily plan — retry once without it before
            # giving up. Otherwise degrade to a notice (the bot still replies).
            if attempt == 1 and payload.pop("country", None):
                continue
            _logger.warning("Tavily search failed: %s", exc)
            return "Web search is currently unavailable."


def _openai_compatible_web_search_run(self, body, inputs, provider_label, post_fn):
    """Drive an OpenAI-compatible chat with a Tavily-backed web_search tool.

    Handles the search sub-loop internally: when the model calls web_search we
    run Tavily and feed the result back; only a final answer or a NON-web_search
    tool call (a real agent tool) is returned to the framework. Returns the
    4-tuple ``(response, to_call, next_inputs, usage)`` like the plain helper.

    Bounded exactly like the Claude loop: at most ``_MAX_CONTINUATIONS`` resume
    rounds and ``_MAX_USES`` total searches, so it can never spin unbounded.
    """
    tools = list(body.get("tools") or ())
    tools.append(_tavily_tool_def())
    body = {**body, "tools": tools, "tool_choice": "auto"}

    messages = list(body["messages"])
    next_inputs = list(inputs or ())
    agg_usage = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}
    searches_used = 0

    for _round in range(_WEB_SEARCH_MAX_CONTINUATIONS_TAVILY + 1):
        data = post_fn({**body, "messages": messages})
        if usage := data.get("usage"):
            agg_usage["input_tokens"] += usage.get("prompt_tokens", 0)
            agg_usage["cached_tokens"] += usage.get("prompt_cache_hit_tokens", 0)
            agg_usage["output_tokens"] += usage.get("completion_tokens", 0)

        message = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        web_calls = [tc for tc in tool_calls if (tc.get("function") or {}).get("name") == _TAVILY_TOOL_NAME]
        other_calls = [tc for tc in tool_calls if (tc.get("function") or {}).get("name") != _TAVILY_TOOL_NAME]

        if not web_calls:
            # Final text, or real agent tool calls to hand back to the framework.
            response, to_call, ni, __ = _parse_openai_compatible_response(
                data, next_inputs, provider_label,
            )
            return response, to_call, ni, agg_usage

        # Model asked to search: stitch the assistant turn + tool results in.
        messages.append(message)
        next_inputs.append(message)
        for tc in web_calls:
            try:
                arguments = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if searches_used < _WEB_SEARCH_MAX_USES_TAVILY:
                result = _run_tavily_search(self.env, arguments.get("query") or "")
                searches_used += 1
                if result is None:  # key vanished mid-loop — treat as unavailable
                    result = "Web search is currently unavailable."
            else:
                result = "Web search limit reached; answer with what you have."
            tool_msg = {"role": "tool", "tool_call_id": tc.get("id"), "content": result}
            messages.append(tool_msg)
            next_inputs.append(tool_msg)

        if other_calls:
            # Real tools alongside the search: defer them to the framework. The
            # web_search results are already stitched into next_inputs, so the
            # continued turn stays protocol-valid (every tool_call answered).
            to_call = _extract_openai_tool_calls(other_calls, provider_label)
            return [], to_call, next_inputs, agg_usage

        if searches_used >= _WEB_SEARCH_MAX_USES_TAVILY:
            break  # hit the search ceiling; one more model turn would be capped

    # Ran out of rounds / searches: ask the model once more for a final answer
    # with search disabled so it cannot loop again.
    final_body = {**body, "messages": messages}
    final_body.pop("tools", None)
    final_body.pop("tool_choice", None)
    data = post_fn(final_body)
    if usage := data.get("usage"):
        agg_usage["input_tokens"] += usage.get("prompt_tokens", 0)
        agg_usage["cached_tokens"] += usage.get("prompt_cache_hit_tokens", 0)
        agg_usage["output_tokens"] += usage.get("completion_tokens", 0)
    _logger.info(
        "%s Tavily search hit its ceiling (%s searches); returning final answer",
        provider_label, searches_used,
    )
    response, to_call, ni, __ = _parse_openai_compatible_response(data, next_inputs, provider_label)
    return response, to_call, ni, agg_usage


def _extract_openai_tool_calls(tool_calls, provider_label):
    """Build the framework's ``to_call`` list from raw OpenAI tool_calls."""
    to_call = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        try:
            arguments = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            _logger.error("AI: Malformed arguments from %s: %s", provider_label, fn)
            continue
        to_call.append((fn.get("name"), tc.get("id"), arguments))
    return to_call


# ---------------------------------------------------------------------------
# DeepSeek — OpenAI-compatible Chat Completions, hosted at api.deepseek.com
# ---------------------------------------------------------------------------

def _request_llm_deepseek(
    self, llm_model, system_prompts, user_prompts, tools=None,
    files=None, schema=None, temperature=0.2, inputs=(), web_grounding=False,
):
    """DeepSeek (Chat Completions). Returns ``(response, to_call, next_inputs)``."""
    _reject_unsupported("deepseek", files, schema)

    messages = _openai_compatible_messages(system_prompts, user_prompts, inputs)
    body = _openai_compatible_body(llm_model, messages, temperature, tools)

    def _post(b):
        return self._request(
            method="post",
            endpoint="/chat/completions",
            headers=self._get_base_headers(),
            body=b,
            timeout=120,
        )

    with api_call_logging(messages, tools) as record_response:
        if web_grounding and _tavily_key(self.env):
            response, to_call, next_inputs, usage = _openai_compatible_web_search_run(
                self, body, inputs, "deepseek", _post,
            )
        else:
            if web_grounding:
                _logger.info(
                    "deepseek: web search requested but no Tavily key is set; "
                    "answering without it",
                )
            response, to_call, next_inputs, usage = _parse_openai_compatible_response(
                _post(body), inputs, "deepseek",
            )
        if record_response:
            record_response(to_call, response, usage)
        return response, to_call, next_inputs


LLMApiService._request_llm_deepseek = _request_llm_deepseek


# ---------------------------------------------------------------------------
# Self-Hosted — OpenAI-compatible Chat Completions against a user-provided
# server (Ollama, vLLM, LM Studio, …). Uses raw requests.post because the
# upstream ``_request`` helper relies on a Bearer token that may be empty
# for local deployments without auth.
# ---------------------------------------------------------------------------

def _request_llm_selfhosted(
    self, llm_model, system_prompts, user_prompts, tools=None,
    files=None, schema=None, temperature=0.2, inputs=(), web_grounding=False,
):
    """Self-Hosted (OpenAI-compatible). Returns ``(response, to_call, next_inputs)``."""
    _reject_unsupported("selfhosted", files, schema)

    messages = _openai_compatible_messages(system_prompts, user_prompts, inputs)
    body = _openai_compatible_body(llm_model, messages, temperature, tools)

    def _post(b):
        """Raw POST to the user's server, returning the parsed JSON dict.
        Uses requests directly because the token may be empty (local Ollama)."""
        headers = selfhosted_request_headers(self._get_api_token())
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=b,
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            error = repr(exc)
            if exc.response is not None:
                try:
                    error = exc.response.json().get("error", {}).get("message") or exc.response.text
                except ValueError:
                    error = exc.response.text
            _logger.warning("Custom LLM request failed (%s): %s", self.base_url, error)
            raise UserError(_(
                "Custom LLM server returned an error: %s",
                error,
            ))
        return resp.json()

    with api_call_logging(messages, tools) as record_response:
        if web_grounding and _tavily_key(self.env):
            response, to_call, next_inputs, usage = _openai_compatible_web_search_run(
                self, body, inputs, "selfhosted", _post,
            )
        else:
            if web_grounding:
                _logger.info(
                    "selfhosted: web search requested but no Tavily key is set; "
                    "answering without it",
                )
            response, to_call, next_inputs, usage = _parse_openai_compatible_response(
                _post(body), inputs, "selfhosted",
            )
        if record_response:
            record_response(to_call, response, usage)
        return response, to_call, next_inputs


LLMApiService._request_llm_selfhosted = _request_llm_selfhosted


# ---------------------------------------------------------------------------
# _build_tool_call_response — branches for all three providers
# ---------------------------------------------------------------------------

_orig_build_tool_call_response = LLMApiService._build_tool_call_response


def _patched_build_tool_call_response(self, tool_call_id, return_value):
    if self.provider == "anthropic":
        return {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": str(return_value),
            }],
        }
    if self.provider in ("deepseek", "selfhosted"):
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(return_value),
        }
    return _orig_build_tool_call_response(self, tool_call_id, return_value)


LLMApiService._build_tool_call_response = _patched_build_tool_call_response
