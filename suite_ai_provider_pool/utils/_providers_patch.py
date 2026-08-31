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

import logging
import typing

from odoo.addons.ai.utils.llm_providers import PROVIDERS, Provider

_logger = logging.getLogger(__name__)

# ``response_style_to_llm_model_and_reasoning`` (added to Provider in Odoo 19) is
# a style -> (replacement_model, reasoning) map read ONLY behind a
# ``llm_model in provider.deprecated_models`` guard
# (llm_providers.get_llm_model_and_reasoning / get_deprecated_model_replacement_label).
# Our providers carry no deprecated_models, so it is never indexed for us and an
# empty mapping is the correct, side-effect-free value. Passed explicitly (below)
# so ``_make_provider`` does NOT treat it as an unknown field and warn on it.
_NO_DEPRECATION_REDIRECT = {}


def _empty_for(annotation):
    """A type-appropriate empty value for a Provider field we don't set.

    Prefer ``{}`` / ``[]`` / ``""`` (matching the field's annotation) over
    ``None`` so upstream code that reads the field tolerantly — ``for x in
    field``, ``field.get(k)``, ``if field:`` — keeps working; only a hard
    ``field[k]`` / ``field.attr`` on a never-populated field would still fail,
    and that is a LOUD runtime error, not a silent one. Unknown types fall back
    to ``None``.
    """
    origin = typing.get_origin(annotation) or annotation
    return {
        dict: {}, list: [], tuple: (), set: set(),
        str: "", int: 0, float: 0.0, bool: False,
    }.get(origin, None)


def _make_provider(**kwargs):
    """Construct ``ai...Provider`` resiliently across 19.x point releases.

    Odoo has already added a *required* field to this NamedTuple between point
    releases (``response_style_to_llm_model_and_reasoning``). Constructing it
    with a fixed argument list means the NEXT such addition raises ``TypeError``
    at import and takes the WHOLE registry — every module, every user — down,
    merely to register a few chat providers. This factory builds the tuple from
    whatever fields the *running* Odoo declares:

    * fields we pass explicitly are used as-is;
    * a field the running Odoo declares but we did NOT pass (an upstream
      *addition*) is filled with ``_empty_for`` and logged as a WARNING, so the
      instance still boots while flagging that someone should check whether our
      providers need a real value;
    * a kwarg that is no longer a Provider field (an upstream *removal*) is
      dropped, also with a WARNING.

    Safe for us because our transport reads only name / display_name /
    embedding_model / llms / deprecated_models; every other Provider field is
    consumed by upstream's own guarded, provider-specific paths. An empty value
    could only ever matter if a future field were read UNCONDITIONALLY on every
    provider in ``PROVIDERS`` — the WARNING is the tripwire for exactly that.
    """
    fields = Provider._fields
    annotations = getattr(Provider, "__annotations__", {})

    removed = sorted(k for k in kwargs if k not in fields)
    if removed:
        _logger.warning(
            "suite_ai_provider_pool: Provider no longer declares %s — dropping "
            "(upstream removed it?). Review utils/_providers_patch.py.",
            ", ".join(removed),
        )

    values = {}
    for name in fields:
        if name in kwargs:
            values[name] = kwargs[name]
            continue
        values[name] = _empty_for(annotations.get(name))
        _logger.warning(
            "suite_ai_provider_pool: upstream added Provider field %r — filled "
            "with %r to keep the registry loading. Review whether our providers "
            "need a real value.", name, values[name],
        )
    return Provider(**values)


ANTHROPIC = _make_provider(
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
    response_style_to_llm_model_and_reasoning=_NO_DEPRECATION_REDIRECT,
)

DEEPSEEK = _make_provider(
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
    response_style_to_llm_model_and_reasoning=_NO_DEPRECATION_REDIRECT,
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

SELFHOSTED = _make_provider(
    name="selfhosted",
    display_name="Custom LLM (OpenAI-compatible)",
    embedding_model="",
    embedding_config={},
    llms=list(SELFHOSTED_DEFAULT_MODELS),
    deprecated_models=[],
    response_style_to_llm_model_and_reasoning=_NO_DEPRECATION_REDIRECT,
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
