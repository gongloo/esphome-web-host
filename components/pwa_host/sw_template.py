from __future__ import annotations

import json


def generate_service_worker(
    cache_prefix: str,
    cache_version: str,
    precache_urls: list[str],
    route_strategies: dict[str, str],
    fallback_urls: list[str],
) -> str:
    """Generate an ESPHome-safe, reverse-proxy-compatible Service Worker script."""
    cache_name = f"{cache_prefix}-{cache_version}"
    cache_prefix_dash = f"{cache_prefix}-"
    route_entries = list(route_strategies.items())

    return f"""const CACHE_PREFIX = {json.dumps(cache_prefix_dash)};
const CACHE_NAME = {json.dumps(cache_name)};
const CACHE_VERSION_LEN = {len(cache_version)};
const PRECACHE_URLS = {json.dumps(precache_urls)};
const ROUTE_ENTRIES = {json.dumps(route_entries)};
const FALLBACK_URLS = {json.dumps(fallback_urls)};

const resolvePath = (asset) => new URL(asset, self.location.href).pathname;
const ROUTE_STRATEGIES = new Map(
  ROUTE_ENTRIES.map(([asset, strategy]) => [resolvePath(asset), strategy])
);
const FALLBACK_PATHS = new Set(FALLBACK_URLS.map(resolvePath));

async function fallbackResponse(req, pathname) {{
  const cached = (await caches.match(req)) || (await caches.match(req, {{ ignoreSearch: true }}));
  if (cached) return cached;
  if (FALLBACK_PATHS.has(pathname)) {{
    for (const url of FALLBACK_URLS) {{
      const match = (await caches.match(url)) || (await caches.match(url, {{ ignoreSearch: true }}));
      if (match) return match;
    }}
  }}
  return Response.error();
}}

function saveToCache(event, req, res) {{
  if (res && res.status === 200) {{
    const clone = res.clone();
    event.waitUntil(
      caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {{}})
    );
  }}
  return res;
}}

function networkFirst(event, req, pathname) {{
  return fetch(req)
    .then((res) => saveToCache(event, req, res))
    .catch(() => fallbackResponse(req, pathname));
}}

async function cacheFirst(event, req, pathname) {{
  const cached = (await caches.match(req)) || (await caches.match(req, {{ ignoreSearch: true }}));
  if (cached) return cached;
  return fetch(req)
    .then((res) => saveToCache(event, req, res))
    .catch(() => fallbackResponse(req, pathname));
}}

async function staleWhileRevalidate(event, req, pathname) {{
  const cached = (await caches.match(req)) || (await caches.match(req, {{ ignoreSearch: true }}));
  const fetchPromise = fetch(req).then((res) => saveToCache(event, req, res));
  if (cached) {{
    event.waitUntil(fetchPromise.catch(() => {{}}));
    return cached;
  }}
  return fetchPromise.catch(() => fallbackResponse(req, pathname));
}}

self.addEventListener('install', (event) => {{
  self.skipWaiting();
  event.waitUntil(
    (async () => {{
      try {{
        const cache = await caches.open(CACHE_NAME);
        for (const url of PRECACHE_URLS) {{
          try {{
            await cache.add(url);
          }} catch (err) {{
            // Ignore individual asset failures (e.g. socket limits on embedded targets)
          }}
        }}
      }} catch (err) {{
        // Ignore cache storage errors
      }}
    }})()
  );
}});

self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => (
          k.startsWith(CACHE_PREFIX)
          && /^[0-9a-f]+$/.test(k.slice(CACHE_PREFIX.length))
          && k.length === CACHE_PREFIX.length + CACHE_VERSION_LEN
          && k !== CACHE_NAME
        )).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener('fetch', (event) => {{
  const req = event.request;
  if (req.method !== 'GET') return;

  let pathname = '';
  try {{
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;
    pathname = url.pathname;
  }} catch (err) {{
    return;
  }}

  const strategy = ROUTE_STRATEGIES.get(pathname);
  if (!strategy) return;

  if (strategy === 'cache_first') {{
    event.respondWith(cacheFirst(event, req, pathname));
  }} else if (strategy === 'stale_while_revalidate') {{
    event.respondWith(staleWhileRevalidate(event, req, pathname));
  }} else {{
    event.respondWith(networkFirst(event, req, pathname));
  }}
}});
"""
