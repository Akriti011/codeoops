"""
LLM service factory for creating configured LLM clients.

Includes a compatibility layer for OpenAI-compatible API proxies that may
return slightly non-standard responses (e.g. choices[].index = None).

Supports multiple providers: openai-compatible, anthropic, bedrock, azure-openai.
"""
import contextlib
import logging
import os
import threading
from openai.types import chat

from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import OpenAI, BadRequestError

from codewiki.src.config import Config

logger = logging.getLogger(__name__)


def _should_use_max_completion_tokens(model_name: str, base_url: str) -> bool:
    """
    Determine whether to use max_completion_tokens instead of max_tokens.

    Newer OpenAI models (o1, o3, o4, gpt-4o, gpt-5, etc.) require
    max_completion_tokens. Anthropic and other providers still use max_tokens.
    """
    model_lower = model_name.lower()
    # OpenAI models that require max_completion_tokens
    new_openai_patterns = ("o1", "o3", "o4", "gpt-4o", "gpt-4-turbo", "gpt-5")
    if any(pattern in model_lower for pattern in new_openai_patterns):
        return True
    # If base_url points to OpenAI directly, newer models may need it
    if base_url and "api.openai.com" in base_url:
        return True
    return False


# A local Ollama instance is single-GPU/CPU and easily overwhelmed by
# concurrent requests (see CodeOops's job orchestration, which can fire more
# than one repository generation at a time). This serializes every Ollama
# call at the process level so "one active generation at a time" holds even
# if the Ollama server itself isn't configured with OLLAMA_NUM_PARALLEL=1.
_ollama_call_lock = threading.Semaphore(1)


def _is_ollama_endpoint(base_url: str) -> bool:
    """Best-effort detection of an Ollama server behind an openai-compatible base_url."""
    if not base_url:
        return False
    lowered = base_url.lower()
    return "11434" in lowered or "ollama" in lowered


def _ollama_extra_body() -> dict:
    """Request a larger Ollama context window (num_ctx) than its runtime default.

    Ollama silently truncates the prompt to whatever context window it loads
    the model with — commonly 2048-4096 tokens regardless of the model's own
    trained context length — unless a request explicitly asks for more via
    ``options.num_ctx``. CodeWiki's documentation prompts (system prompt +
    module tree + component relationships + source code for several files)
    routinely exceed that default, so most of the prompt — including the
    documentation instructions themselves — was silently being dropped
    before the model ever saw it. This restores the intended behavior:
    the model actually receiving what CodeWiki sends it.
    """
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    return {"options": {"num_ctx": num_ctx}}


def _llm_request_timeout(base_url: str) -> float:
    """HTTP client timeout (seconds) for a single LLM request.

    The openai SDK's own default (600s) is tuned for hosted, GPU-backed
    inference. Local CPU-bound Ollama inference — especially a larger-context
    model working through a multi-turn tool-calling loop — routinely needs
    longer than that per call; without an explicit override, generation was
    failing with openai.APITimeoutError well before CodeOops's own much more
    generous job-level timeout was ever at risk.
    """
    # Measured directly against this deployment's Ollama instance: a plain
    # 800-completion-token request did not finish within 1200s (well under
    # 1 token/sec). The spec's original 600-800s target assumed throughput
    # this hardware doesn't currently deliver — rather than guess a number
    # between "confirmed too short" and "unknown", this is set generously
    # above the slowest measured point so real generations actually
    # complete instead of reliably hitting OVERVIEW_GENERATION_TIMEOUT.
    # Tighten via LLM_REQUEST_TIMEOUT_SECONDS once real hardware throughput
    # (or a faster model) is confirmed to need less.
    default_timeout = 3600.0 if _is_ollama_endpoint(base_url) else 600.0
    return float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", str(default_timeout)))


def _build_model_settings(config: Config, model_name: str) -> OpenAIChatModelSettings:
    """Build model settings with the correct token parameter."""
    extra_body = _ollama_extra_body() if _is_ollama_endpoint(config.llm_base_url) else None
    timeout = _llm_request_timeout(config.llm_base_url)

    if _should_use_max_completion_tokens(model_name, config.llm_base_url):
        return OpenAIChatModelSettings(
            temperature=0.0,
            max_completion_tokens=config.max_tokens,
            timeout=timeout,
            **({"extra_body": extra_body} if extra_body else {}),
        )
    return OpenAIChatModelSettings(
        temperature=0.0,
        max_tokens=config.max_tokens,
        timeout=timeout,
        **({"extra_body": extra_body} if extra_body else {}),
    )


def _get_litellm_model_name(model_name: str, provider: str) -> str:
    """
    Get the litellm-compatible model name for a given provider.

    For Bedrock, prefixes the model name with 'bedrock/' if not already prefixed.
    For Anthropic, prefixes with 'anthropic/' if not already prefixed.
    """
    if provider == "bedrock":
        if not model_name.startswith("bedrock/"):
            return f"bedrock/{model_name}"
    elif provider == "anthropic":
        if not model_name.startswith("anthropic/"):
            return f"anthropic/{model_name}"
    return model_name


class CompatibleOpenAIModel(OpenAIChatModel):
    """OpenAIChatModel subclass that patches non-standard API proxy responses.

    Some OpenAI-compatible proxies return responses with fields like
    choices[].index set to None instead of an integer. This subclass
    fixes those fields before pydantic validation runs.
    """

    def _validate_completion(self, response: chat.ChatCompletion) -> chat.ChatCompletion:
        # Patch choices[].index: None -> sequential integer (0, 1, 2, ...)
        if response.choices:
            for i, choice in enumerate(response.choices):
                if choice.index is None:
                    choice.index = i
        return super()._validate_completion(response)


def _create_litellm_openai_client(config: Config) -> OpenAI:
    """
    Create an OpenAI-compatible client backed by litellm's proxy.

    litellm translates OpenAI API calls to Bedrock, Anthropic, etc.
    """
    # Configure litellm for the provider
    if config.provider == "bedrock":
        import os
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)

    # litellm exposes an OpenAI-compatible Router we can use,
    # but the simplest path is to use litellm.completion() directly.
    # For pydantic-ai integration, we create a proxy client.
    return OpenAI(
        api_key=config.llm_api_key or "not-needed-for-bedrock",
        base_url=config.llm_base_url or "https://api.openai.com/v1",
    )


def create_main_model(config: Config) -> CompatibleOpenAIModel:
    """Create the main LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.main_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.main_model)
    )


def create_fallback_model(config: Config) -> CompatibleOpenAIModel:
    """Create the fallback LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.fallback_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.fallback_model)
    )


def create_fallback_models(config: Config) -> FallbackModel:
    """Create fallback models chain from configuration."""
    main = create_main_model(config)
    fallback = create_fallback_model(config)
    return FallbackModel(main, fallback)


def create_openai_client(config: Config) -> OpenAI:
    """Create OpenAI client from configuration.

    ``max_retries=0``: the openai SDK's default (2 retries — 3 attempts
    total) is meant for transient network blips against hosted, GPU-backed
    inference. Against local CPU-bound Ollama inference, a timeout means the
    model genuinely needs longer, not that the request should be replayed —
    retrying just multiplies the wait (observed: a single attempt exhausting
    its full timeout, then the SDK silently trying twice more, tripling time
    to failure) with zero chance of a different outcome. A hard, singleshot
    timeout is what the resource-bounding contract in documentation_generator
    (overview_only mode) actually needs: fail once, fail fast, fail loudly.
    """
    return OpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        timeout=_llm_request_timeout(config.llm_base_url),
        max_retries=0,
    )


def call_llm(
    prompt: str,
    config: Config,
    model: str = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> str:
    """
    Call LLM with the given prompt.

    Supports openai-compatible, anthropic, and bedrock providers.
    For bedrock/anthropic, uses litellm to translate the API call.

    Args:
        prompt: The prompt to send
        config: Configuration containing LLM settings
        model: Model name (defaults to config.main_model)
        temperature: Temperature setting
        max_tokens: Output token cap for this call (defaults to config.max_tokens).
            Lets a caller request a smaller bounded response — e.g. a single
            repository overview — without changing the global default used by
            other generation paths.

    Returns:
        LLM response text
    """
    if model is None:
        model = config.main_model
    if max_tokens is None:
        max_tokens = config.max_tokens

    provider = getattr(config, "provider", "openai-compatible")

    if provider in ("bedrock", "anthropic"):
        return _call_llm_via_litellm(prompt, config, model, temperature)

    if provider == "azure-openai":
        return _call_llm_via_azure(prompt, config, model, temperature)

    # Default: OpenAI-compatible
    client = create_openai_client(config)

    # Use the correct token parameter based on model/provider; if the server
    # rejects our choice, swap to the other token kwarg and retry once.
    use_completion_tokens = _should_use_max_completion_tokens(model, config.llm_base_url)
    primary_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
    fallback_key = "max_tokens" if use_completion_tokens else "max_completion_tokens"

    base_kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    is_ollama = _is_ollama_endpoint(config.llm_base_url)
    if is_ollama:
        base_kwargs["extra_body"] = _ollama_extra_body()

    with _ollama_call_lock if is_ollama else contextlib.nullcontext():
        try:
            response = client.chat.completions.create(
                **base_kwargs,
                **{primary_key: max_tokens},
            )
        except BadRequestError as e:
            if _is_unsupported_token_param_error(e, primary_key):
                logger.info(
                    "Provider rejected %s for model %s; retrying with %s.",
                    primary_key, model, fallback_key,
                )
                response = client.chat.completions.create(
                    **base_kwargs,
                    **{fallback_key: max_tokens},
                )
            else:
                raise
    return response.choices[0].message.content


def _is_unsupported_token_param_error(err: BadRequestError, param: str) -> bool:
    """Return True if *err* is the OpenAI "unsupported_parameter" error for *param*."""
    body = getattr(err, "body", None) or {}
    if isinstance(body, dict):
        error = body.get("error") or {}
        if isinstance(error, dict):
            if error.get("param") == param and error.get("code") == "unsupported_parameter":
                return True
    # Fallback: message-based sniff for proxies that don't preserve structure
    msg = str(err).lower()
    return "unsupported parameter" in msg and param in msg


def _call_llm_via_litellm(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via litellm for Bedrock/Anthropic providers.

    litellm handles the provider-specific API translation automatically.
    """
    import litellm
    import os

    litellm_model = _get_litellm_model_name(model, config.provider)

    if config.provider == "bedrock":
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)
        logger.debug("Calling Bedrock model %s in region %s", litellm_model, config.aws_region)
    elif config.provider == "anthropic":
        logger.debug("Calling Anthropic model %s via litellm", litellm_model)

    response = litellm.completion(
        model=litellm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
        api_key=config.llm_api_key if config.provider != "bedrock" else None,
    )
    return response.choices[0].message.content


def _call_llm_via_azure(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via Azure OpenAI.

    Uses the AzureOpenAI client from the openai package with
    azure_endpoint, api_version, and deployment name.
    """
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=config.llm_api_key,
        api_version=config.api_version,
        azure_endpoint=config.llm_base_url,
    )

    deployment = config.azure_deployment or model
    logger.debug("Calling Azure OpenAI deployment %s (api_version=%s)", deployment, config.api_version)

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content
