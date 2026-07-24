"""Register Anthropic Claude, DeepSeek, and Self-Hosted as additional LLM providers.

Extends the module-level ``PROVIDERS`` list in
``odoo.addons.ai.utils.llm_providers``. ``EMBEDDING_MODELS_SELECTION`` is
built once at import of that module from its initial PROVIDERS list, so
providers appended here do not surface in embedding selection — which is
the intent (this module ships chat models only).

The Self-Hosted provider's ``llms`` list is mutated at runtime when the
administrator saves new custom model identifiers in AI Settings — see
``models/res_config_settings.py``.
"""

from odoo.addons.ai.utils.llm_providers import PROVIDERS, Provider

ANTHROPIC = Provider(
    name="anthropic",
    display_name="Anthropic Claude",
    embedding_model="",
    embedding_config={},
    llms=[
        ("claude-opus-4-8", "Claude Opus 4.8"),
        ("claude-opus-4-7", "Claude Opus 4.7"),
        ("claude-opus-4-6", "Claude Opus 4.6"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
        ("claude-haiku-4-5", "Claude Haiku 4.5"),
    ],
    deprecated_models=[],
)

DEEPSEEK = Provider(
    name="deepseek",
    display_name="DeepSeek",
    embedding_model="",
    embedding_config={},
    # DeepSeek retired the deepseek-chat / deepseek-reasoner API names; the
    # platform now serves deepseek-v4-pro and deepseek-v4-flash (verified live
    # 2026-07-24 — the API rejects the old names outright), so we list only the
    # models that actually work.
    llms=[
        ("deepseek-v4-pro", "DeepSeek V4 Pro"),
        ("deepseek-v4-flash", "DeepSeek V4 Flash"),
    ],
    deprecated_models=[],
)

# Curated defaults for Self-Hosted. Tags follow the conventions of Ollama,
# vLLM and LM Studio; exotic or fine-tuned models are added by the user
# through AI Settings (see ``suite_selfhosted_models``).
SELFHOSTED_DEFAULT_MODELS = [
    ("llama3.3:70b", "Llama 3.3 70B"),
    ("qwen3:32b", "Qwen3 32B"),
    ("qwen2.5:72b", "Qwen 2.5 72B"),
    ("deepseek-v3", "DeepSeek V3 (self-hosted)"),
    ("deepseek-r1", "DeepSeek R1 (self-hosted)"),
    ("gpt-oss:120b", "GPT-OSS 120B"),
    ("gpt-oss:20b", "GPT-OSS 20B"),
    ("mistral-small", "Mistral Small"),
    ("gemma3:27b", "Gemma 3 27B"),
    ("phi4", "Phi-4"),
]

SELFHOSTED = Provider(
    name="selfhosted",
    display_name="Self-Hosted (OpenAI-compatible)",
    embedding_model="",
    embedding_config={},
    llms=list(SELFHOSTED_DEFAULT_MODELS),
    deprecated_models=[],
)


def _register():
    existing_names = {p.name for p in PROVIDERS}
    for prov in (ANTHROPIC, DEEPSEEK, SELFHOSTED):
        if prov.name not in existing_names:
            PROVIDERS.append(prov)


_register()


def refresh_selfhosted_models(custom_models):
    """Replace the Self-Hosted provider's model list with curated defaults
    plus the given custom entries.

    ``custom_models`` is an iterable of ``(model_id, display_label)``
    tuples coming from saved settings. Curated defaults always remain
    first; custom entries follow, deduplicated by model_id.
    """
    seen = {model_id for model_id, __ in SELFHOSTED_DEFAULT_MODELS}
    merged = list(SELFHOSTED_DEFAULT_MODELS)
    for model_id, label in custom_models:
        if model_id and model_id not in seen:
            merged.append((model_id, label or model_id))
            seen.add(model_id)
    SELFHOSTED.llms[:] = merged
