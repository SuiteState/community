# -*- coding: utf-8 -*-
from odoo import api, fields, models


# The primary and failover model dropdowns are built dynamically from the
# native LLM provider registry (see ``_get_translate_model_selection``), so
# every provider registered with Odoo's ``ai`` module appears automatically —
# OpenAI and Google out of the box, plus Anthropic Claude, DeepSeek and any
# self-hosted / third-party provider added by another module (e.g. the free
# AI Provider Pool). Any chat model works for translation; it is plain text
# in, plain text out, with no embedding or file requirement.

# Single source of truth for default models. ``mail_message.py``
# imports these for its ICP fallback values so the defaults stay
# consistent across the Settings UI and runtime behavior.
DEFAULT_PRIMARY_MODEL = 'gpt-5-mini'
DEFAULT_FAILOVER_MODEL = 'gemini-2.5-flash'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sat_enabled = fields.Boolean(
        string='Enable Discuss AI Translate',
        default=False,
        config_parameter='suite_ai_translate.enabled',
        help="Enable AI-powered translation in Discuss messages. "
             "When enabled, message text selected for translation will be "
             "sent to the configured AI provider over HTTPS. No other data "
             "is transmitted. Translation text "
             "is cached locally in Odoo (auto-vacuumed after 2 weeks) to "
             "minimize repeat API calls. You must review your organization's "
             "data handling policies and the providers' terms before enabling.",
    )

    sat_llm_model = fields.Selection(
        selection="_get_translate_model_selection",
        string='Translation Model',
        default=DEFAULT_PRIMARY_MODEL,
        config_parameter='suite_ai_translate.llm_model',
        help="Primary model used for translating Discuss messages. "
             "GPT-5 Mini (the default) offers the best balance of "
             "quality, speed, and cost for conversational translation. "
             "Switch to a larger model only if you observe quality "
             "issues with specific language pairs.",
    )

    sat_llm_failover_model = fields.Selection(
        selection="_get_translate_model_selection",
        string='Failover Model',
        default=DEFAULT_FAILOVER_MODEL,
        config_parameter='suite_ai_translate.llm_failover_model',
        help="Model used as automatic fallback when the primary model's "
             "provider fails (network error, rate limit, invalid key). "
             "Pick a model from a DIFFERENT provider than the primary — "
             "failing over to the same provider gives no real resilience. "
             "Only triggered if the other provider has an API key configured.",
    )

    @api.model
    def _get_translate_model_selection(self):
        """Every chat model registered with the native ``ai`` module, so
        third-party providers (Anthropic Claude, DeepSeek, self-hosted, or
        any added by another module such as AI Provider Pool) appear in the
        dropdown automatically alongside the built-in OpenAI and Google
        models. Mirrors the native provider registry; no hardcoded list."""
        from odoo.addons.ai.utils.llm_providers import PROVIDERS
        selection = []
        for provider in PROVIDERS:
            selection.extend(provider.llms)
        return selection
