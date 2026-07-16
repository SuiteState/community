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

MVP scope: chat only. The ``files``, ``schema`` and ``web_grounding``
parameters raise ``UserError`` for our providers — they are out of
scope for the first release and require provider-specific work.
"""

import json
import logging
import os

import requests

from odoo import _
from odoo.exceptions import UserError
from odoo.addons.ai.utils.ai_logging import api_call_logging
from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils.llm_providers import check_model_depreciation

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

# Sampling parameters that newer Anthropic models (Opus 4.7+, Fable 5) reject
# with a 400. We send temperature by default; if the API refuses it we strip
# these and retry once. Model-agnostic on purpose (keyed on the API's own 400,
# not a hardcoded model list) so future models are handled without changes.
_SAMPLING_KEYS = ("temperature", "top_p", "top_k")


def normalize_selfhosted_url(raw):
    """Best-effort normalization of a user-entered server URL: strip
    whitespace and trailing slash, prepend ``http://`` when no scheme is
    given, and append ``/v1`` when the path does not already end with
    it. Returns an empty string if ``raw`` is falsy."""
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    if not raw.endswith("/v1"):
        raw = raw + "/v1"
    return raw


def _resolve_selfhosted_base_url(env):
    """Resolve the Self-Hosted base URL from saved settings. Raises a
    user-facing error when the URL is not configured."""
    raw = env["ir.config_parameter"].sudo().get_param(_SELFHOSTED_URL_PARAM, "")
    base_url = normalize_selfhosted_url(raw)
    if not base_url:
        raise UserError(_(
            "Self-Hosted AI server URL is not configured. "
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


def _reject_unsupported(provider, files, schema, web_grounding):
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
    if web_grounding:
        raise UserError(_(
            "Provider '%s' does not support web grounding in this module. "
            "Use OpenAI or Gemini for web-grounded chats.",
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
# _request_llm — dispatcher extension (deprecation check kept at top)
# ---------------------------------------------------------------------------

_orig_request_llm = LLMApiService._request_llm


def _patched_request_llm(self, *args, **kwargs):
    if self.provider in ("anthropic", "deepseek", "selfhosted"):
        model = kwargs.get("llm_model") or args[0]
        check_model_depreciation(self.env, model)
        if self.provider == "anthropic":
            return self._request_llm_anthropic(*args, **kwargs)
        if self.provider == "deepseek":
            return self._request_llm_deepseek(*args, **kwargs)
        return self._request_llm_selfhosted(*args, **kwargs)
    return _orig_request_llm(self, *args, **kwargs)


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
    _reject_unsupported("anthropic", files, schema, web_grounding)

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
    if tools:
        body["tools"] = _anthropic_tool_schema(tools)

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

    response = []
    to_call = []
    next_inputs = list(inputs or ())

    has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)

    for block in content_blocks:
        btype = block.get("type")
        if btype == "tool_use":
            to_call.append((block.get("name"), block.get("id"), block.get("input") or {}))
        elif btype == "text" and not has_tool_use:
            if text := block.get("text"):
                response.append(text)

    if content_blocks:
        next_inputs.append({"role": "assistant", "content": content_blocks})

    request_token_usage = {}
    if usage := data.get("usage"):
        request_token_usage["input_tokens"] = usage.get("input_tokens", 0)
        request_token_usage["cached_tokens"] = (
            usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        request_token_usage["output_tokens"] = usage.get("output_tokens", 0)

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
# DeepSeek — OpenAI-compatible Chat Completions, hosted at api.deepseek.com
# ---------------------------------------------------------------------------

def _request_llm_deepseek(
    self, llm_model, system_prompts, user_prompts, tools=None,
    files=None, schema=None, temperature=0.2, inputs=(), web_grounding=False,
):
    """DeepSeek (Chat Completions). Returns ``(response, to_call, next_inputs)``."""
    _reject_unsupported("deepseek", files, schema, web_grounding)

    messages = _openai_compatible_messages(system_prompts, user_prompts, inputs)
    body = _openai_compatible_body(llm_model, messages, temperature, tools)

    with api_call_logging(messages, tools) as record_response:
        response, to_call, next_inputs, request_token_usage = self._request_llm_deepseek_helper(body, inputs)
        if record_response:
            record_response(to_call, response, request_token_usage)
        return response, to_call, next_inputs


def _request_llm_deepseek_helper(self, body, inputs=()):
    data = self._request(
        method="post",
        endpoint="/chat/completions",
        headers=self._get_base_headers(),
        body=body,
    )
    return _parse_openai_compatible_response(data, inputs, "deepseek")


LLMApiService._request_llm_deepseek = _request_llm_deepseek
LLMApiService._request_llm_deepseek_helper = _request_llm_deepseek_helper


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
    _reject_unsupported("selfhosted", files, schema, web_grounding)

    messages = _openai_compatible_messages(system_prompts, user_prompts, inputs)
    body = _openai_compatible_body(llm_model, messages, temperature, tools)

    with api_call_logging(messages, tools) as record_response:
        response, to_call, next_inputs, request_token_usage = self._request_llm_selfhosted_helper(body, inputs)
        if record_response:
            record_response(to_call, response, request_token_usage)
        return response, to_call, next_inputs


def _request_llm_selfhosted_helper(self, body, inputs=()):
    headers = selfhosted_request_headers(self._get_api_token())
    try:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=body,
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
        _logger.warning("Self-Hosted AI request failed (%s): %s", self.base_url, error)
        raise UserError(_(
            "Self-Hosted AI server returned an error: %s",
            error,
        ))
    return _parse_openai_compatible_response(resp.json(), inputs, "selfhosted")


LLMApiService._request_llm_selfhosted = _request_llm_selfhosted
LLMApiService._request_llm_selfhosted_helper = _request_llm_selfhosted_helper


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
