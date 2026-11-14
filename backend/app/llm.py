"""Unified LLM wrapper supporting Gemini, Groq, and Ollama.

All LLM calls throughout the application MUST go through this module.
Secrets are never printed, logged, or echoed in error messages.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Optional, Union

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when the configured LLM provider is unavailable, unconfigured, or fails."""

    def __init__(self, message: str, code: str = "llm_unavailable") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _sanitize_message(message: str, secret: Optional[str] = None) -> str:
    """Ensure no secret token appears in error messages or logs."""
    if secret and secret in message:
        message = message.replace(secret, "[REDACTED]")
    return message


def _classify_error(exc: Exception, secret: Optional[str] = None) -> tuple[str, str]:
    """Classify exception into a standard code and sanitized message."""
    raw_msg = str(exc)
    msg = _sanitize_message(raw_msg, secret)
    lower = msg.lower()

    if any(k in lower for k in ("api_key_invalid", "invalid api key", "unauthenticated", "401", "403", "forbidden")):
        return "invalid_api_key", f"Invalid API key: {msg}"
    if any(k in lower for k in ("not_found", "404", "model not found", "does not exist")):
        return "model_not_found", f"Model not found: {msg}"
    if any(k in lower for k in ("resource_exhausted", "429", "rate limit", "quota exceeded")):
        return "rate_limited", f"Rate limited: {msg}"
    if any(k in lower for k in ("connect", "connection", "dns", "timeout", "timed out", "network")):
        return "network_error", f"Network error: {msg}"

    return "llm_unavailable", msg


def _generate_gemini(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call Google Gemini API via the google-genai SDK."""
    settings = get_settings()
    raw_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    api_key = raw_key.strip() if raw_key else ""
    if not api_key:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured", "missing_api_key")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise LLMUnavailableError("google-genai package is not installed", "sdk_missing") from exc

    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
        )

        if stream:
            def _stream_iterator() -> Iterator[str]:
                try:
                    response = client.models.generate_content_stream(
                        model=settings.gemini_model,
                        contents=prompt,
                        config=config,
                    )
                    for chunk in response:
                        if chunk.text:
                            yield chunk.text
                except Exception as e:
                    code, clean_msg = _classify_error(e, api_key)
                    logger.warning("Gemini streaming error: %s", clean_msg)
                    raise LLMUnavailableError(f"Gemini streaming failed: {clean_msg}", code) from e

            return _stream_iterator()

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
        )
        if not response or not response.text:
            return ""
        return response.text
    except LLMUnavailableError:
        raise
    except Exception as exc:
        code, clean_msg = _classify_error(exc, api_key)
        raise LLMUnavailableError(clean_msg, code) from exc


def _generate_groq(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call Groq API using the groq SDK."""
    settings = get_settings()
    raw_key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    api_key = raw_key.strip() if raw_key else ""
    if not api_key:
        raise LLMUnavailableError("GROQ_API_KEY is not configured", "missing_api_key")

    try:
        from groq import Groq
    except ImportError as exc:
        raise LLMUnavailableError("groq package is not installed", "sdk_missing") from exc

    try:
        client = Groq(api_key=api_key, timeout=settings.llm_timeout_seconds)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if stream:
            def _stream_iterator() -> Iterator[str]:
                try:
                    completion = client.chat.completions.create(
                        model=settings.groq_model,
                        messages=messages,
                        temperature=0.2,
                        stream=True,
                    )
                    for chunk in completion:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content
                except Exception as e:
                    code, clean_msg = _classify_error(e, api_key)
                    logger.warning("Groq streaming error: %s", clean_msg)
                    raise LLMUnavailableError(f"Groq streaming failed: {clean_msg}", code) from e

            return _stream_iterator()

        completion = client.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            temperature=0.2,
            stream=False,
        )
        return completion.choices[0].message.content or ""
    except LLMUnavailableError:
        raise
    except Exception as exc:
        code, clean_msg = _classify_error(exc, api_key)
        raise LLMUnavailableError(clean_msg, code) from exc


def _generate_ollama(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call local Ollama instance via HTTP requests."""
    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    import json
    import httpx

    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": stream,
        "options": {"temperature": 0.2},
    }
    if system:
        payload["system"] = system

    if stream:
        def _stream_iterator() -> Iterator[str]:
            try:
                with httpx.stream(
                    "POST",
                    f"{base_url}/api/generate",
                    json=payload,
                    timeout=settings.llm_timeout_seconds,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if line:
                            data = json.loads(line)
                            yield data.get("response", "")
            except Exception as e:
                code, clean_msg = _classify_error(e)
                logger.warning("Ollama streaming error: %s", clean_msg)
                raise LLMUnavailableError(f"Ollama streaming failed: {clean_msg}", code) from e

        return _stream_iterator()

    try:
        resp = httpx.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except Exception as exc:
        code, clean_msg = _classify_error(exc)
        raise LLMUnavailableError(f"Ollama request failed: {clean_msg}", code) from exc


def generate(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Generate completion using the configured LLM provider with retries.

    Parameters
    ----------
    prompt:
        User prompt text.
    system:
        Optional system instructions.
    stream:
        Whether to stream tokens via an iterator.

    Returns
    -------
    Text completion or generator of tokens.

    Raises
    ------
    LLMUnavailableError:
        If the provider fails or API keys are missing.
    """
    settings = get_settings()
    provider = settings.llm_provider.lower()
    max_retries = settings.llm_max_retries

    dispatch = {
        "gemini": _generate_gemini,
        "groq": _generate_groq,
        "ollama": _generate_ollama,
    }

    if provider not in dispatch:
        raise LLMUnavailableError(f"Unknown LLM provider: {provider}", "unknown_provider")

    fn = dispatch[provider]

    # For streaming, return iterator immediately (caller handles iteration)
    if stream:
        return fn(prompt, system=system, stream=True)

    # For non-streaming, perform retries with exponential backoff on transient errors
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(prompt, system=system, stream=False)
        except LLMUnavailableError as err:
            # Don't retry non-transient configuration/auth errors
            if err.code in ("missing_api_key", "invalid_api_key", "model_not_found", "unknown_provider", "sdk_missing"):
                raise
            last_err = err
        except Exception as exc:  # noqa: BLE001
            last_err = exc

        if attempt < max_retries:
            backoff = 2 ** attempt
            logger.info("Retrying LLM call in %ss (attempt %d/%d)", backoff, attempt + 1, max_retries)
            time.sleep(backoff)

    raise LLMUnavailableError(f"LLM call failed after {max_retries + 1} attempts: {last_err}") from last_err
