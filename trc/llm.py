from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import openai

logger = logging.getLogger("trc.llm")


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Call the LLM with the given parameters."""
        pass


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI and OpenRouter (which uses OpenAI-compatible API)."""

    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        logger.debug(f"Initialized OpenAI provider with base_url={base_url}")

    def call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        logger.debug(f"Calling OpenAI LLM with model={model}, temperature={temperature}, max_tokens={max_tokens}")
        logger.debug(f"Messages: {len(messages)} messages")
        for i, msg in enumerate(messages):
            logger.debug(f"Message {i}: {msg['role']} - {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            logger.debug(f"OpenAI response received: {len(content)} characters")
            logger.debug(f"Response preview: {content[:200]}{'...' if len(content) > 200 else ''}")
            return content
        except Exception as e:
            logger.error(f"OpenAI LLM call failed: {e}")
            raise


class AzureProvider(LLMProvider):
    """Provider for Azure AI Foundry."""

    def __init__(self, api_key: str, endpoint: str, api_version: str = "2024-02-01"):
        self.client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
        logger.debug(f"Initialized Azure provider with endpoint={endpoint}, api_version={api_version}")

    def call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        logger.debug(f"Calling Azure LLM with model={model}, temperature={temperature}, max_tokens={max_tokens}")
        logger.debug(f"Messages: {len(messages)} messages")
        for i, msg in enumerate(messages):
            logger.debug(f"Message {i}: {msg['role']} - {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            logger.debug(f"Azure response received: {len(content)} characters")
            logger.debug(f"Response preview: {content[:200]}{'...' if len(content) > 200 else ''}")
            return content
        except Exception as e:
            logger.error(f"Azure LLM call failed: {e}")
            raise


class LLMClient:
    """Main LLM client that abstracts provider switching."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def call_llm(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Call LLM with a simple prompt interface."""
        logger.debug(f"LLMClient.call_llm called with model={model}, system_prompt={'present' if system_prompt else 'none'}")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self.provider.call_llm(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    def call_llm_json(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call LLM and parse response as JSON."""
        response = self.call_llm(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            **kwargs,
        )
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {response}") from e

    def call_llm_with_prompt_file(
        self,
        prompt_file: str | Path,
        **template_vars: Any,
    ) -> str:
        """Call LLM using a prompt file with metadata."""
        logger.info(f"Calling LLM with prompt file: {prompt_file}")
        template = PromptTemplate(prompt_file)
        prompt = template.render(**template_vars)
        params = template.get_llm_params()

        return self.call_llm(prompt=prompt, **params)

    def call_llm_json_with_prompt_file(
        self,
        prompt_file: str | Path,
        **template_vars: Any,
    ) -> dict[str, Any]:
        """Call LLM using a prompt file with metadata and expect JSON response."""
        logger.info(f"Calling LLM with prompt file (JSON expected): {prompt_file}")
        template = PromptTemplate(prompt_file)
        prompt = template.render(**template_vars)
        params = template.get_llm_params()

        return self.call_llm_json(prompt=prompt, **params)


def create_provider(provider_config: dict[str, Any]) -> LLMProvider:
    """Factory function to create LLM providers from config."""
    provider_type = provider_config.get("type", "openai")

    if provider_type == "openai":
        return OpenAIProvider(
            api_key=provider_config["api_key"],
            base_url=provider_config.get("base_url"),
        )
    elif provider_type == "azure":
        return AzureProvider(
            api_key=provider_config["api_key"],
            endpoint=provider_config["endpoint"],
            api_version=provider_config.get("api_version", "2024-02-01"),
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def create_client_from_config(llm_config: dict[str, Any]) -> LLMClient:
    """Create LLM client from configuration."""
    provider = create_provider(llm_config["provider"])
    return LLMClient(provider)


def parse_prompt_file(prompt_path: str | Path) -> tuple[dict[str, Any], str]:
    """Parse a prompt file with metadata header.

    Returns (metadata_dict, prompt_content)
    """
    path = Path(prompt_path)
    logger.debug(f"Parsing prompt file: {prompt_path}")
    if not path.exists():
        logger.error(f"Prompt file not found: {prompt_path}")
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    content = path.read_text(encoding="utf-8")

    # Split on --- markers
    parts = content.split("---")
    if len(parts) < 3:
        logger.error(f"Invalid prompt file format: {prompt_path}. Expected --- metadata --- prompt ---")
        raise ValueError(f"Invalid prompt file format: {prompt_path}. Expected --- metadata --- prompt ---")

    # Extract metadata (YAML/JSON between first two ---)
    metadata_text = parts[1].strip()
    try:
        # Try to parse as JSON first
        metadata = json.loads(metadata_text)
        logger.debug(f"Parsed metadata as JSON: {metadata}")
    except json.JSONDecodeError:
        # If not JSON, try to parse as simple YAML-like format
        metadata = {}
        for line in metadata_text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # Handle nested parameters
                if key == "parameters":
                    # Parse indented parameters
                    param_lines = []
                    for param_line in metadata_text.split("\n"):
                        if param_line.strip().startswith("parameters:"):
                            continue
                        if param_line.startswith("  ") and ":" in param_line:
                            param_lines.append(param_line.strip())

                    params = {}
                    for param_line in param_lines:
                        if ":" in param_line:
                            p_key, p_value = param_line.split(":", 1)
                            p_key = p_key.strip()
                            p_value = p_value.strip()
                            # Convert numeric values
                            try:
                                if "." in p_value:
                                    params[p_key] = float(p_value)
                                else:
                                    params[p_key] = int(p_value)
                            except ValueError:
                                params[p_key] = p_value
                    metadata[key] = params
                else:
                    # Convert simple values
                    try:
                        if value.lower() in ("true", "false"):
                            metadata[key] = value.lower() == "true"
                        elif value.isdigit():
                            metadata[key] = int(value)
                        elif "." in value and value.replace(".", "").isdigit():
                            metadata[key] = float(value)
                        else:
                            metadata[key] = value
                    except ValueError:
                        metadata[key] = value

    # Extract prompt content (everything after second ---)
    prompt_content = "---".join(parts[2:]).strip()
    logger.debug(f"Parsed prompt content: {len(prompt_content)} characters")

    return metadata, prompt_content


def render_prompt_template(prompt_template: str, **variables: Any) -> str:
    """Render a prompt template with variables."""
    result = prompt_template
    for key, value in variables.items():
        placeholder = "{{" + key + "}}"
        result = result.replace(placeholder, str(value))
    return result


class PromptTemplate:
    """A prompt template loaded from a file with metadata."""

    def __init__(self, prompt_path: str | Path):
        logger.debug(f"Loading prompt template from: {prompt_path}")
        self.metadata, self.template = parse_prompt_file(prompt_path)
        self.prompt_path = Path(prompt_path)
        logger.info(f"Loaded prompt template '{self.description}' from {prompt_path}")

    def render(self, **variables: Any) -> str:
        """Render the template with variables."""
        logger.debug(f"Rendering prompt template with variables: {list(variables.keys())}")
        result = render_prompt_template(self.template, **variables)
        logger.debug(f"Rendered prompt: {len(result)} characters")
        return result

    def get_llm_params(self) -> dict[str, Any]:
        """Get LLM parameters from metadata."""
        params = self.metadata.get("parameters", {}).copy()

        # Extract model from model_id_ref (e.g., "openai/gpt-4o-mini" -> "gpt-4o-mini")
        model_ref = self.metadata.get("model_id_ref", "")
        if "/" in model_ref:
            # Remove quotes if present and split
            clean_ref = model_ref.strip('"')
            params["model"] = clean_ref.split("/", 1)[1]
        else:
            params["model"] = model_ref.strip('"')

        logger.debug(f"LLM parameters for {self.prompt_path.name}: {params}")
        return params

    @property
    def force_json_output(self) -> bool:
        """Whether the prompt expects JSON output."""
        return self.metadata.get("force_json_output", False)

    @property
    def description(self) -> str:
        """Description of the prompt."""
        return self.metadata.get("description", "")
