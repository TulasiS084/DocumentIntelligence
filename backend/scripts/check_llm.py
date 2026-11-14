"""CLI diagnostic script to verify LLM configuration without exposing secrets.

Usage:
    cd backend
    python scripts/check_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import get_settings
from app.llm import LLMUnavailableError, generate


def run_check() -> int:
    """Execute LLM connectivity and configuration check."""
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        model = settings.gemini_model
        key_configured = settings.is_gemini_key_configured
        key_var = "GEMINI_API_KEY"
    elif provider == "groq":
        model = settings.groq_model
        key_configured = settings.is_groq_key_configured
        key_var = "GROQ_API_KEY"
    else:
        model = settings.ollama_model
        key_configured = True
        key_var = None

    print(f"Configured Provider: {provider}")
    print(f"Configured Model:    {model}")
    print(f"API key configured:  {'yes' if key_configured else 'no'}")

    if not key_configured:
        print("\nStatus: FAILED")
        print(f"Error: missing key - {key_var} is not set in backend/.env")
        print(f"Fix: Open backend/.env and paste your API key at: {key_var}=your_key_here")
        return 1

    print("\nSending test prompt to LLM...")
    try:
        reply = generate("Respond with the single word: OK", temperature=0.1, max_tokens=10)
        clean_reply = str(reply).strip()
        print("Status: SUCCESS")
        print(f"LLM OK: {clean_reply}")
        return 0
    except LLMUnavailableError as exc:
        print("\nStatus: FAILED")
        code = exc.code
        msg = exc.message

        if code == "missing_api_key":
            print(f"Error: missing key - {key_var} is empty or missing.")
            print(f"Fix: Open backend/.env and paste your API key at: {key_var}=your_key_here")
        elif code == "invalid_api_key":
            print("Error: invalid key - The provider rejected your API key as invalid or unauthorized.")
            if provider == "gemini":
                print("Fix: Get a valid key at https://aistudio.google.com/app/apikey and ensure no trailing spaces in backend/.env.")
            else:
                print("Fix: Check your API key in backend/.env and ensure there are no trailing spaces or quotes.")
        elif code == "model_not_found":
            print(f"Error: model not found - Model '{model}' was not found or is unavailable for provider '{provider}'.")
            print("Fix: Check the model name in backend/.env (e.g. GEMINI_MODEL=gemini-2.5-flash).")
        elif code == "rate_limited":
            print("Error: rate limited - Request exceeded quota or rate limit.")
            print("Fix: Wait 60 seconds before retrying or review quota in your provider dashboard.")
        elif code == "network_error":
            print("Error: network error - Could not establish connection to the provider API.")
            print("Fix: Check your internet connection, DNS resolution, or firewall settings.")
        else:
            print(f"Error: {code} - {msg}")
            print("Fix: Review provider status and backend/.env settings.")
        return 1
    except Exception as exc:
        print("\nStatus: FAILED")
        print(f"Error: unexpected error - {exc}")
        print("Fix: Check backend logs and network connectivity.")
        return 1


if __name__ == "__main__":
    sys.exit(run_check())
