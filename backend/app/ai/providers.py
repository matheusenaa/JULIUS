"""Provedores de IA intercambiáveis (AI_PROVIDER=gemini | openai | none).

A IA só devolve JSON com interpretações/redação. Nenhum cálculo financeiro é
delegado a ela. Qualquer falha vira AIUnavailable e o sistema segue sem IA.
"""

import base64
import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("julius.ai")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class AIUnavailable(Exception):
    pass


class AIProvider(Protocol):
    name: str

    def generate_json(
        self, system: str, prompt: str, image: bytes | None = None, mime: str | None = None
    ) -> dict: ...


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIUnavailable("Resposta da IA não é JSON válido") from exc
    if not isinstance(data, dict):
        raise AIUnavailable("Resposta da IA em formato inesperado")
    return data


class GeminiProvider:
    name = "gemini"

    def __init__(self, s: Settings):
        if not s.gemini_api_key:
            raise AIUnavailable("GEMINI_API_KEY não configurada")
        self.key = s.gemini_api_key
        self.model = s.ai_model or "gemini-flash-latest"
        self.timeout = s.ai_timeout_seconds

    def generate_json(self, system, prompt, image=None, mime=None) -> dict:
        parts: list[dict] = [{"text": prompt}]
        if image:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}})
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        url = f"{GEMINI_BASE}/models/{self.model}:generateContent"
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.key}, timeout=self.timeout)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("Gemini indisponível: %s", type(exc).__name__)
            raise AIUnavailable(str(type(exc).__name__)) from exc
        return _parse_json(text)

    def chat(self, messages: list[dict], tools: list[dict]) -> "ChatReply":
        # Endpoint do Gemini compatível com OpenAI (suporta function calling)
        return _openai_chat(
            f"{GEMINI_BASE}/openai/chat/completions", self.key, self.model, self.timeout, messages, tools
        )


class OpenAICompatibleProvider:
    """OpenAI, Groq, OpenRouter, Ollama local, LM Studio… (API /chat/completions)."""

    name = "openai"

    def __init__(self, s: Settings):
        local = "localhost" in s.openai_base_url or "127.0.0.1" in s.openai_base_url
        if not s.openai_api_key and not local:
            raise AIUnavailable("OPENAI_API_KEY não configurada")
        self.key = s.openai_api_key or "local"
        self.base = s.openai_base_url.rstrip("/")
        self.model = s.ai_model or "gpt-4o-mini"
        self.timeout = s.ai_timeout_seconds

    def generate_json(self, system, prompt, image=None, mime=None) -> dict:
        content: list[dict] | str = prompt
        if image:
            data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        body = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        }
        try:
            r = httpx.post(
                f"{self.base}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("Provedor OpenAI-compatível indisponível: %s", type(exc).__name__)
            raise AIUnavailable(str(type(exc).__name__)) from exc
        return _parse_json(text)

    def chat(self, messages: list[dict], tools: list[dict]) -> "ChatReply":
        return _openai_chat(
            f"{self.base}/chat/completions", self.key, self.model, self.timeout, messages, tools
        )


_provider_override: AIProvider | None = None


def set_provider_for_tests(provider: AIProvider | None) -> None:
    global _provider_override
    _provider_override = provider


@dataclass
class ChatReply:
    text: str | None
    tool_calls: list[dict]  # [{"id", "name", "arguments": dict}]
    raw_message: dict


def _openai_chat(
    url: str, key: str, model: str, timeout: float, messages: list[dict], tools: list[dict]
) -> ChatReply:
    body = {"model": model, "temperature": 0.2, "messages": messages}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    try:
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("Chat com ferramentas indisponível: %s", type(exc).__name__)
        raise AIUnavailable(type(exc).__name__) from exc
    calls = []
    for c in msg.get("tool_calls") or []:
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(
            {"id": c.get("id") or c["function"]["name"], "name": c["function"]["name"], "arguments": args}
        )
    return ChatReply(text=msg.get("content"), tool_calls=calls, raw_message=msg)


def get_provider_for(user) -> AIProvider | None:
    """Provedor respeitando a preferência do usuário (IA pode ser desligada em Ajustes)."""
    if (getattr(user, "settings", None) or {}).get("ai_enabled") is False:
        return None
    return get_provider()


def get_provider() -> AIProvider | None:
    """Provedor configurado, ou None quando a IA está desligada/sem chave."""
    if _provider_override is not None:
        return _provider_override
    s = get_settings()
    try:
        if s.ai_provider == "gemini":
            return GeminiProvider(s)
        if s.ai_provider == "openai":
            return OpenAICompatibleProvider(s)
    except AIUnavailable as exc:
        log.warning("IA desativada: %s", exc)
    return None
