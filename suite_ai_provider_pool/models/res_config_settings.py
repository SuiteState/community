import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils._api_service_patch import (
    normalize_selfhosted_url,
    selfhosted_request_headers,
)
from ..utils._providers_patch import refresh_selfhosted_models

_SELFHOSTED_PROBE_TIMEOUT = 15  # seconds — fetching /v1/models is interactive
_SELFHOSTED_MODELS_PARAM = "ai.selfhosted_models"


def _parse_selfhosted_models_text(text):
    """Parse the ``suite_selfhosted_models`` textarea into ``(model_id,
    label)`` tuples. Each non-empty, non-comment line is one entry; the
    optional ``|`` separator splits the model identifier from a friendly
    display label.

    Examples::

        qwen2.5:14b
        qwen2.5:72b | Qwen 2.5 72B (production)
        # everything after a hash is ignored
    """
    entries = []
    seen = set()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "|" in line:
            model_id, __, label = line.partition("|")
            model_id = model_id.strip()
            label = label.strip() or model_id
        else:
            model_id = line
            label = line
        if model_id and model_id not in seen:
            entries.append((model_id, label))
            seen.add(model_id)
    return entries


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    suite_anthropic_key = fields.Char(
        string="Anthropic API Key",
        config_parameter="ai.anthropic_key",
        help=(
            "API key used for Anthropic Claude chat models. "
            "Get one at console.anthropic.com. "
            "If the environment variable ODOO_AI_ANTHROPIC_TOKEN is set, "
            "it overrides this value."
        ),
    )
    suite_deepseek_key = fields.Char(
        string="DeepSeek API Key",
        config_parameter="ai.deepseek_key",
        help=(
            "API key used for DeepSeek chat models. "
            "Get one at platform.deepseek.com. "
            "If the environment variable ODOO_AI_DEEPSEEK_TOKEN is set, "
            "it overrides this value."
        ),
    )
    suite_selfhosted_url = fields.Char(
        string="Self-Hosted Server URL",
        config_parameter="ai.selfhosted_url",
        help=(
            "Base URL of an OpenAI-compatible inference server: Ollama, "
            "vLLM, LM Studio, or any other endpoint that exposes "
            "/v1/chat/completions. The /v1 suffix is added automatically "
            "if you only type host:port. Examples: "
            "http://localhost:11434, http://192.168.1.10:8000."
        ),
    )
    suite_selfhosted_key = fields.Char(
        string="Self-Hosted API Key",
        config_parameter="ai.selfhosted_key",
        help=(
            "Optional bearer token for servers that require authentication. "
            "Leave empty for local Ollama instances without auth. "
            "If the environment variable ODOO_AI_SELFHOSTED_TOKEN is set, "
            "it overrides this value."
        ),
    )
    suite_tavily_key = fields.Char(
        string="Tavily API Key",
        config_parameter="ai.tavily_key",
        help=(
            "Optional. Enables web search for DeepSeek and self-hosted models "
            "(which have no built-in search) via Tavily. Get a key at "
            "tavily.com. Not needed for OpenAI, Gemini or Claude, which search "
            "natively. Results are localized to your company's country. "
            "If the environment variable ODOO_AI_TAVILY_TOKEN is set, it "
            "overrides this value. Leave empty to disable Tavily search."
        ),
    )
    suite_server_action_model = fields.Selection(
        selection="_get_llm_model_selection",
        string="AI Automation Model",
        config_parameter="suite_ai_provider_pool.server_action_model",
        help=(
            "Model for Odoo's built-in AI automations (server actions / "
            "rules flagged 'AI', document sorting) — NOT the chatbot; AI "
            "Agents and the WhatsApp AI keep their own model. Odoo defaults "
            "to OpenAI GPT-4.1; set this to use Claude, DeepSeek or "
            "self-hosted. Leave empty to keep the default (needs an OpenAI key)."
        ),
    )

    @api.model
    def _get_llm_model_selection(self):
        from odoo.addons.ai.utils.llm_providers import PROVIDERS
        selection = []
        for provider in PROVIDERS:
            selection.extend(provider.llms)
        return selection

    suite_selfhosted_models = fields.Text(
        string="Self-Hosted Custom Models",
        help=(
            "Additional model identifiers exposed in the AI Agent model "
            "selector, one per line. Use the format expected by your "
            "server (e.g. 'qwen2.5:14b' for Ollama). Add '| Display Name' "
            "after the identifier to set a friendly label. Use the "
            "Fetch Available Models button to populate this list "
            "automatically."
        ),
    )

    # ------------------------------------------------------------------
    # Lifecycle: refresh the in-memory provider model list on save so
    # custom models become selectable in AI Agents without a restart.
    # ------------------------------------------------------------------

    @api.model
    def get_values(self):
        res = super().get_values()
        res["suite_selfhosted_models"] = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(_SELFHOSTED_MODELS_PARAM, "")
        )
        return res

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            _SELFHOSTED_MODELS_PARAM,
            self.suite_selfhosted_models or "",
        )
        text = self.env["ir.config_parameter"].sudo().get_param(_SELFHOSTED_MODELS_PARAM, "")
        refresh_selfhosted_models(_parse_selfhosted_models_text(text))

    @api.model
    def _register_hook(self):
        """At server start, push any persisted custom models into the
        Self-Hosted provider so the dropdown is correct on first use."""
        result = super()._register_hook()
        text = self.env["ir.config_parameter"].sudo().get_param(_SELFHOSTED_MODELS_PARAM, "")
        refresh_selfhosted_models(_parse_selfhosted_models_text(text))
        return result

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _suite_selfhosted_probe_models(self):
        """Call ``GET {base_url}/models`` and return the list of model
        identifiers. Raises ``UserError`` with a clear message on any
        connectivity, auth or protocol failure."""
        self.ensure_one()
        base_url = normalize_selfhosted_url(self.suite_selfhosted_url)
        if not base_url:
            raise UserError(_("Fill in the Self-Hosted Server URL first."))
        headers = selfhosted_request_headers(self.suite_selfhosted_key or "")
        try:
            resp = requests.get(
                f"{base_url}/models",
                headers=headers,
                timeout=_SELFHOSTED_PROBE_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            detail = repr(exc)
            if exc.response is not None:
                try:
                    detail = exc.response.json().get("error", {}).get("message") or exc.response.text
                except ValueError:
                    detail = exc.response.text
            raise UserError(_(
                "Could not reach %(url)s: %(detail)s",
                url=base_url,
                detail=detail,
            ))
        try:
            payload = resp.json()
        except ValueError:
            raise UserError(_(
                "Server at %s returned a non-JSON response — is this an "
                "OpenAI-compatible endpoint?",
                base_url,
            ))
        items = payload.get("data") or []
        ids = [item.get("id") for item in items if isinstance(item, dict) and item.get("id")]
        if not ids:
            raise UserError(_(
                "Server at %s did not list any models. Make sure at least "
                "one model is loaded.",
                base_url,
            ))
        return base_url, ids

    def action_suite_test_selfhosted_connection(self):
        base_url, ids = self._suite_selfhosted_probe_models()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Self-Hosted AI connection OK"),
                "message": _(
                    "Reached %(url)s, %(count)d model(s) available.",
                    url=base_url,
                    count=len(ids),
                ),
                "sticky": False,
            },
        }

    def action_suite_fetch_selfhosted_models(self):
        base_url, ids = self._suite_selfhosted_probe_models()
        existing = {m_id for m_id, __ in _parse_selfhosted_models_text(self.suite_selfhosted_models)}
        new_ids = [m_id for m_id in ids if m_id not in existing]
        if new_ids:
            current_text = (self.suite_selfhosted_models or "").rstrip()
            separator = "\n" if current_text else ""
            self.suite_selfhosted_models = current_text + separator + "\n".join(new_ids)
            message = _(
                "Added %(added)d new model(s) from %(url)s. Click Save to "
                "make them selectable in your AI Agents.",
                added=len(new_ids),
                url=base_url,
            )
            notif_type = "success"
        else:
            message = _(
                "No new models — all %(count)d model(s) on %(url)s are "
                "already in the list.",
                count=len(ids),
                url=base_url,
            )
            notif_type = "info"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notif_type,
                "title": _("Self-Hosted models fetched"),
                "message": message,
                "sticky": False,
            },
        }
