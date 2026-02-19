from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from langchain_openai import AzureChatOpenAI


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@lru_cache(maxsize=1)
def build_chat_model() -> AzureChatOpenAI:
    endpoint = _required_env("AZURE_OPENAI_ENDPOINT")
    deployment = _required_env("AZURE_OPENAI_CHAT_DEPLOYMENT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")

    model_kwargs: dict[str, Any] = {
        "azure_endpoint": endpoint,
        "azure_deployment": deployment,
        "api_version": api_version,
        "temperature": 0,
        "max_retries": 2,
    }

    if api_key:
        model_kwargs["api_key"] = api_key
    else:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        model_kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default",
        )

    return AzureChatOpenAI(**model_kwargs)


def model_debug_config() -> dict[str, str]:
    return {
        "azure_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "azure_api_version": os.getenv("AZURE_OPENAI_API_VERSION", ""),
        "azure_chat_deployment": os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", ""),
        "auth_mode": "api_key" if os.getenv("AZURE_OPENAI_API_KEY") else "managed_identity",
    }
