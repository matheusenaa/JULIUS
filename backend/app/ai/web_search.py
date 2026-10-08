"""Busca na web opcional para o agente de IA.

Suporta provedores gratuitos: Tavily, Serper, Brave Search ou DuckDuckGo HTML.
Configurar via variáveis de ambiente. Se nenhum provedor estiver configurado,
retorna erro indicando que busca não está disponível.
"""

import json
import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger("julius.ai.web_search")

MAX_RESULTS = 8
MAX_CHARS = 8000


def _truncate(text: str, max_chars: int = MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[...truncado...]\n"


class WebSearchError(Exception):
    pass


def _search_tavily(query: str) -> dict[str, Any]:
    s = get_settings()
    api_key = s.tavily_api_key
    if not api_key:
        raise WebSearchError("Tavily não configurado")
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": MAX_RESULTS,
                "include_answer": False,
                "include_raw_content": False,
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Tavily search failed: %s", type(exc).__name__)
        raise WebSearchError("Falha na busca (Tavily)") from exc
    results = []
    for res in data.get("results", [])[:MAX_RESULTS]:
        results.append(
            {
                "title": res.get("title", ""),
                "url": res.get("url", ""),
                "snippet": res.get("content", "") or res.get("snippet", ""),
            }
        )
    return {"provider": "tavily", "results": results}


def _search_serper(query: str) -> dict[str, Any]:
    s = get_settings()
    api_key = s.serper_api_key
    if not api_key:
        raise WebSearchError("Serper não configurado")
    try:
        r = httpx.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": MAX_RESULTS},
            headers={"X-API-KEY": api_key},
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Serper search failed: %s", type(exc).__name__)
        raise WebSearchError("Falha na busca (Serper)") from exc
    results = []
    for res in data.get("organic", [])[:MAX_RESULTS]:
        results.append(
            {
                "title": res.get("title", ""),
                "url": res.get("link", ""),
                "snippet": res.get("snippet", "") or res.get("summary", ""),
            }
        )
    return {"provider": "serper", "results": results}


def _search_brave(query: str) -> dict[str, Any]:
    s = get_settings()
    api_key = s.brave_api_key
    if not api_key:
        raise WebSearchError("Brave não configurado")
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": MAX_RESULTS, "mkt": "pt-BR"},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Brave search failed: %s", type(exc).__name__)
        raise WebSearchError("Falha na busca (Brave)") from exc
    results = []
    web = data.get("web", {})
    for res in web.get("results", [])[:MAX_RESULTS]:
        results.append(
            {
                "title": res.get("title", ""),
                "url": res.get("url", ""),
                "snippet": res.get("description", "") or res.get("snippet", ""),
            }
        )
    return {"provider": "brave", "results": results}


def _search_duckduckgo(query: str) -> dict[str, Any]:
    try:
        r = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20.0,
            follow_redirects=True,
        )
        r.raise_for_status()
        html = r.text
    except httpx.HTTPError as exc:
        log.warning("DuckDuckGo search failed: %s", type(exc).__name__)
        raise WebSearchError("Falha na busca (DuckDuckGo)") from exc
    results: list[dict[str, str]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select(".result__a")[:MAX_RESULTS]:
            href = a.get("href", "")
            if href.startswith("/"):
                continue
            title = a.get_text(strip=True)
            snippet_tag = a.find_next("a", class_="result__snippet")
            if not snippet_tag:
                snippet_tag = a.parent.find_next(class_="result__snippet") if a.parent else None
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            if href:
                results.append({"title": title, "url": href, "snippet": snippet})
    except Exception as exc:
        log.warning("DuckDuckGo parse failed: %s", type(exc).__name__)
        raise WebSearchError("Falha ao processar resultados de busca") from exc
    return {"provider": "duckduckgo", "results": results}


def search_web(query: str) -> dict[str, Any]:
    if not query or not query.strip():
        raise WebSearchError("Consulta vazia")
    q = query.strip()
    s = get_settings()
    providers_order = [p.strip() for p in s.web_search_provider_order.split(",") if p.strip()]
    errors: list[str] = []
    for provider in providers_order:
        try:
            if provider == "tavily":
                res = _search_tavily(q)
            elif provider == "serper":
                res = _search_serper(q)
            elif provider == "brave":
                res = _search_brave(q)
            elif provider == "duckduckgo":
                res = _search_duckduckgo(q)
            else:
                continue
            res["query"] = q
            res["summary"] = _truncate(
                "\n\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})" for r in res["results"])
            )
            return res
        except WebSearchError as exc:
            errors.append(str(exc))
            continue
    raise WebSearchError(errors[0] if errors else "Nenhum provedor de busca configurado")
