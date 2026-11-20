"""Connecteur universel pour la partie agent (archiviste + narrateur).

Toute API compatible avec l'API OpenAI Chat Completions convient : OpenAI, Mistral, OpenRouter,
Groq, Google Gemini, Anthropic, Ollama (local), ou une URL personnalisée. Les fournisseurs ne
gèrent pas tous les mêmes paramètres : si l'un d'eux refuse la température, le mode JSON ou
max_tokens, la requête est relancée sans ce paramètre plutôt que d'échouer.

Les embeddings (recherche sémantique) restent ceux d'OpenAI : les bases RAG ont été indexées
avec text-embedding-3-small, la question doit donc être encodée par le même modèle.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from openai import BadRequestError, OpenAI

OPENAI_BASE_URL = "https://api.openai.com/v1"

# Paramètres optionnels qu'un fournisseur peut refuser, et leur éventuel remplaçant.
_DROPPABLE = {
    "temperature": None,
    "response_format": None,
    "max_tokens": "max_completion_tokens",   # certains modèles OpenAI récents
}


class CompatClient:
    """Client compatible OpenAI, tolérant aux paramètres non pris en charge."""

    def __init__(self, base_url: str | None, api_key: str | None):
        self.base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
        # Ollama et certains serveurs locaux n'exigent pas de clé, mais le SDK en veut une.
        self.raw = OpenAI(base_url=self.base_url, api_key=api_key or "not-needed")
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = self.raw.models

    def _create(self, **kwargs):
        for _ in range(len(_DROPPABLE) + 1):
            try:
                return self.raw.chat.completions.create(**kwargs)
            except BadRequestError as exc:
                message = str(exc).lower()
                culprit = next((p for p in _DROPPABLE if p in kwargs and p in message), None)
                if culprit is None:
                    raise
                value = kwargs.pop(culprit)
                if _DROPPABLE[culprit]:
                    kwargs[_DROPPABLE[culprit]] = value
                print(f"[LLM] paramètre « {culprit} » refusé par le fournisseur : relance sans")
        return self.raw.chat.completions.create(**kwargs)

    def list_models(self) -> list[str]:
        """Modèles de dialogue proposés par le fournisseur (sans embeddings, audio, image, modération)."""
        ids = {m.id.removeprefix("models/") for m in self.raw.models.list()}   # Gemini préfixe « models/ »
        return sorted(i for i in ids if not _NON_CHAT.search(i))


# Modèles listés par /models mais inutilisables pour dialoguer.
_NON_CHAT = re.compile(r"embed|whisper|tts|dall-e|image|moderation|audio|realtime|transcribe|"
                       r"davinci|babbage|search|similarity|rerank|guard|vision-preview|aqa", re.IGNORECASE)


def is_openai(base_url: str | None) -> bool:
    return not base_url or "api.openai.com" in base_url


def parse_json_object(text: str) -> dict:
    """JSON d'une réponse de modèle, même entouré de texte ou d'un bloc ```json (fournisseurs sans mode JSON)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
