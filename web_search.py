import os
from typing import TypedDict
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()


class WebSource(TypedDict):
    title: str
    url: str
    content: str


def search_web(query: str, max_results: int = 5) -> list[WebSource]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Add it to the project's .env file."
        )

    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    results = payload.get("results")
    if not isinstance(results, list):
        raise RuntimeError("Tavily returned an invalid search response.")

    sources: list[WebSource] = []
    for result in results:
        if not isinstance(result, dict):
            continue

        title = result.get("title")
        url = result.get("url")
        content = result.get("content")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (title, url, content)
        ):
            continue

        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue

        sources.append(
            {
                "title": title.strip(),
                "url": url.strip(),
                "content": content.strip()[:2000],
            }
        )

    return sources
