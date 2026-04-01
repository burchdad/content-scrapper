"""Optional LLM enrichment for legal references.

Provider selection priority:
1. OpenAI (if OPENAI_API_KEY exists)
2. Anthropic (if ANTHROPIC_API_KEY exists)

If neither key is available (or calls fail), callers should continue without AI.
"""

import json
import os
import re
from typing import Any

import httpx


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from free-form LLM text."""
    if not text:
        return None

    text = text.strip()
    # Common case: model returned pure JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Fallback: find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


class LegalAIEnricher:
    """Lightweight HTTP-based enrichment wrapper for OpenAI/Anthropic."""

    def __init__(
        self,
        *,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        timeout_seconds: int = 25,
    ):
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self.timeout_seconds = timeout_seconds

        if self.openai_api_key:
            self.provider = "openai"
        elif self.anthropic_api_key:
            self.provider = "anthropic"
        else:
            self.provider = None

    @property
    def enabled(self) -> bool:
        return bool(self.provider)

    async def enrich(
        self,
        *,
        case_name: str,
        court_name: str,
        query: str,
        snippet: str,
        docket_number: str,
        date_filed: str,
    ) -> dict[str, Any] | None:
        if not self.provider:
            return None

        prompt = (
            "You are a legal-intelligence analyst. "
            "Return ONLY JSON with keys: summary, indicators, risk_adjustment, confidence, reasoning. "
            "- summary: <= 35 words, neutral, factual\n"
            "- indicators: array of 0-6 items from [victimization,recruitment,transport,coercion,exploitation,missing_person,smuggling,violence,financial_crime]\n"
            "- risk_adjustment: number from -10 to 15\n"
            "- confidence: number 0..1\n"
            "- reasoning: <= 25 words\n"
            "Do not accuse people of crimes; frame as potential indicators only.\n\n"
            f"Case: {case_name}\n"
            f"Court: {court_name}\n"
            f"Filed: {date_filed or 'unknown'}\n"
            f"Docket: {docket_number or 'n/a'}\n"
            f"Query match: {query}\n"
            f"Snippet: {snippet[:1200]}\n"
        )

        if self.provider == "openai":
            return await self._enrich_openai(prompt)
        return await self._enrich_anthropic(prompt)

    async def _enrich_openai(self, prompt: str) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = (
            (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
            or ""
        )
        parsed = _extract_json_object(content)
        if not parsed:
            return None
        parsed["provider"] = "openai"
        return parsed

    async def _enrich_anthropic(self, prompt: str) -> dict[str, Any] | None:
        headers = {
            "x-api-key": self.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 300,
            "temperature": 0.1,
            "system": "Return strict JSON only.",
            "messages": [{"role": "user", "content": prompt}],
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        parts = data.get("content") or []
        text = ""
        if parts and isinstance(parts, list):
            text = "\n".join(str(part.get("text") or "") for part in parts)

        parsed = _extract_json_object(text)
        if not parsed:
            return None
        parsed["provider"] = "anthropic"
        return parsed
