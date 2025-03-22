# APICache

A lightweight proxy-cache that sits between your app and a public API.

It helps avoid rate limits, enables reproducible experiments, and incrementally builds up datasets by caching structured responses — **not raw HTTP**.

Solving the frustration of API rate limits, inconsistent responses, and unreproducible workflows by caching structured API responses during development for reuse, graphing, and analysis.


## Installation

```bash
pip install apicache
```

Behind the scenes:
- All API responses are cached in a local SQLite store
- Cached responses are versioned with timestamps and TTL-aware
- The system gracefully falls back to live data when needed
- Cached entries can be purged, inspected, or used to reconstruct state


## Basic Usage

```python
"""proxied-cache to UK govs Companies House API"""
from cache import APICache
import requests
import os

API_KEY = os.environ["COMPANIES_HOUSE_API_KEY"]
BASE_URL = "https://api.company-information.service.gov.uk"

def fetch_from_ch_api(url, params):
    """function to call on cache miss"""
    full_url = url.format(**{**params, "BASE_URL": BASE_URL})
    response = requests.get(full_url, auth=(API_KEY, ""))
    if response.status_code != 200:
        raise ValueError(f"Failed [{response.status_code}]")
    return response.json()

# define the cache object
cache = APICache(request_fn=fetch_from_ch_api, ttl=3600)

# make a request to the backend API
# cache miss will call the `fetch_from_ch_api` function
cache_hit, data = cache.request("{BASE_URL}/company/{company_number}", {"company_number": "12345678"})
print("Cache hit?", cache_hit)
print("Company:", data["company_name"])
print("Stats:", cache.stats())
```

## Use Cases

- Data scientists experimenting with public APIs
- Reproducible research pipelines without rate-limit worries
- Mockable APIs for CI/offline testing
- API usage minimization or budgeting
- Building incremental graphs or datasets over time


## Examples

### Google News RSS

```python
import feedparser
from cache import APICache

def fetch_google_news(url, params):
    query = params["q"]
    full_url = f"https://news.google.com/rss/search?q={query}"
    return feedparser.parse(full_url)

cache = APICache(request_fn=fetch_google_news, ttl=86400)

hit, parsed = cache.request("https://news.google.com/rss/search?q={q}", {"q": "next high tide"})
for entry in parsed["entries"]:
    print(entry["title"])
```

### GitHub API (with headers)

```python
import requests
from cache import APICache

def fetch_github(url, params):
    full_url = url.format(**params)
    resp = requests.get(full_url, headers={"Accept": "application/vnd.github+json"})
    return resp.json()

cache = APICache(request_fn=fetch_github)

hit, user = cache.request("https://api.github.com/users/{username}", {"username": "torvalds"})
print("Name:", user["name"])
```


## Extended usage

The cache indexs over `url: str` and `params: dict`, so any data may be cached via this method.
Cache misses are resolved with the `fetch_fn` callback, which can custom process any actual interaction with the backend API.

### Slow Fibonacci

Of course, you should explore other caching options like `functools.lru_cache` but it is sometimes useful to capture the cached data.

```python
from cache import APICache
import time

def slow_fib(_, params):
    """Pretend this is a slow remote call."""
    n = params["n"]
    time.sleep(0.2)  # simulate latency
    if n <= 1:
        return n
    return fib_cache.request("fib", {"n": n - 1})[1] + fib_cache.request("fib", {"n": n - 2})[1]

fib_cache = APICache(request_fn=slow_fib)

for i in range(20):
    hit, result = fib_cache.request("fib", {"n": i})
    print(f"fib({i}) = {result} {'(cache hit)' if hit else '(computed)'}")

print("\nCache stats:", fib_cache.stats())
```

### OpenAI library calls

In this example, we wrap the `APICache` in a simple object to proxy the `OpenAI` backend without losing the rich object responses defined in the OpenAI library.

**NB: not fully tested**


```python
import openai
from openai.util import convert_to_openai_object
from cache import APICache
import hashlib
import json


class OpenAICache:
    def __init__(self, ttl: int = 86400, location: str = None):
        self.cache = APICache(request_fn=self._fetch_from_openai, ttl=ttl, location=location)

    def _fetch_from_openai(self, key: str, params: dict):
        if key == "openai:chat":
            response = openai.ChatCompletion.create(**params)
        elif key == "openai:image":
            response = openai.Image.create(**params)
        else:
            raise ValueError(f"Unsupported OpenAI API type in key: {key}")

        return response.to_dict()

    def chat(self, **params):
        """Cached chat completion"""
        hit, raw = self.cache.request("openai:chat", params)
        return convert_to_openai_object(raw), hit

    def image(self, **params):
        """Cached image generation"""
        hit, raw = self.cache.request("openai:image", params)
        return convert_to_openai_object(raw), hit

```


# API Reference

```python
cache = APICache(request_fn, ttl=3600, location="api-cache.sqlite")

cache.request(url, params) → (hit: bool, response: dict)
cache.read(url, params)
cache.write(url, params, response)
cache.has(url, params)
cache.clear_for_url("/some/api/prefix")
cache.prune_old_versions()
cache.stats() → dict
```
