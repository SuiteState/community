"""Embedding fallback for providers without an embedding model.

Anthropic, DeepSeek, and Self-Hosted providers registered by this
module do not ship an embedding model (they are chat-only).  The
native ``_get_embedding_model()`` looks up the agent's own provider
and raises ``UserError`` when no embedding model is found there.

This override implements a transparent fallback: when the agent's
provider has no embedding model, the method returns the first
available embedding model from any configured provider (typically
OpenAI or Google).  The user only needs *one* embedding-capable API
key alongside their chosen chat key.

If *no* embedding provider has a key configured, the method raises a
clear ``UserError`` directing the user to Settings > AI.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils.llm_providers import PROVIDERS


class AiAgent(models.Model):
    _inherit = "ai.agent"

    suite_web_search_enabled = fields.Boolean(
        string="Search the Web",
        default=False,
        help=(
            "Let this agent search the web when answering. Odoo has no built-in "
            "toggle for this — the Provider Pool wires it for every provider: "
            "OpenAI and Gemini use their native web search, Claude uses its "
            "server-side search, and DeepSeek / self-hosted models use Tavily "
            "(set a Tavily API key in Settings → AI). OpenAI and Tavily "
            "results are localized to your company's country automatically. "
            "Gemini cannot combine web search with tools, so it is skipped "
            "silently when the agent has tools attached. Off by default."
        ),
    )

    def _generate_response(self, prompt, chat_history=None, extra_system_context=""):
        """Inject web grounding for agents that opt in.

        Native ``_generate_response`` calls ``request_llm`` without
        ``web_grounding`` (Odoo never turns it on), so we flag it through the
        context and let the patched ``request_llm`` (see
        ``utils/_api_service_patch``) pick it up. Done via context rather than a
        method rewrite so we never duplicate the native body.
        """
        agent = self
        if self.suite_web_search_enabled:
            agent = self.with_context(ai_web_grounding=True)
        return super(AiAgent, agent)._generate_response(
            prompt, chat_history=chat_history, extra_system_context=extra_system_context,
        )

    def _get_embedding_model(self):
        """Return the embedding model for this agent's provider, falling
        back to any provider that has both an embedding model and a
        configured API key."""
        self.ensure_one()
        provider = self._get_provider()

        # 1. Agent's own provider has an embedding model — use it
        for p in PROVIDERS:
            if p.name == provider and p.embedding_model:
                return p.embedding_model

        # 2. Fallback: first provider with an embedding model + valid key
        for p in PROVIDERS:
            if not p.embedding_model:
                continue
            try:
                LLMApiService(self.env, p.name)._get_api_token()
                return p.embedding_model
            except UserError:
                continue

        # 3. Nothing available — clear error message
        raise UserError(_(
            "Knowledge Sources require an OpenAI or Google API key for "
            "text embedding. Your current chat model does not include an "
            "embedding service. Please configure an OpenAI or Google key "
            "in Settings > AI."
        ))
