"""Shopify adapter: the keyless /products.json trick.

Many independent retailers run Shopify, which exposes the full catalog at
<base>/products.json with exact variant price and stock status. No JS rendering, no API key, no
model in the loop -> zero hallucination by construction. If a store is not Shopify or blocks the
endpoint, fetch() raises a clear error and the caller can fall back to another adapter.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

UA = "Mozilla/5.0 (agent-gates intake-engine; research use)"


@dataclass
class Variant:
    title: str
    price: str          # price string as Shopify returns it; currency is per-STORE, see currency()
    available: bool
    sku: str = ""
    compare_at_price: str = ""   # Shopify's was-price; enables clearance % detection


@dataclass
class Product:
    title: str
    vendor: str
    url: str
    variants: list[Variant] = field(default_factory=list)

    @property
    def in_stock(self) -> bool:
        return any(v.available for v in self.variants)

    @property
    def price_range(self) -> str:
        prices = sorted({v.price for v in self.variants if v.price})
        if not prices:
            return "?"
        return prices[0] if len(prices) == 1 else f"{prices[0]}-{prices[-1]}"

    @property
    def best_discount_pct(self) -> float:
        """Largest clearance % across variants where compare_at_price > price. 0 if none on sale."""
        best = 0.0
        for v in self.variants:
            try:
                p, c = float(v.price), float(v.compare_at_price)
            except (TypeError, ValueError):
                continue
            if c > p > 0:
                best = max(best, (c - p) / c * 100)
        return round(best, 1)


def _get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch(base_url: str, *, max_pages: int = 4, timeout: int = 25) -> list[Product]:
    """Pull the catalog from <base_url>/products.json. Raises on non-Shopify / blocked stores."""
    base = base_url.rstrip("/")
    products: list[Product] = []
    for page in range(1, max_pages + 1):
        url = f"{base}/products.json?limit=250&page={page}"
        try:
            raw = _get(url, timeout)
        except urllib.error.HTTPError as e:
            if page == 1:
                raise RuntimeError(f"HTTP {e.code} on {url} (not Shopify or blocked)") from e
            break
        except Exception as e:  # noqa: BLE001 - surface the real reason to the caller
            raise RuntimeError(f"{type(e).__name__}: {e} on {url}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"non-JSON response from {url} (not Shopify)") from e
        page_products = data.get("products", [])
        if not page_products:
            break
        for p in page_products:
            handle = p.get("handle", "")
            prod = Product(
                title=p.get("title", "").strip(),
                vendor=(p.get("vendor", "") or "").strip(),
                url=f"{base}/products/{handle}" if handle else base,
                variants=[
                    Variant(
                        title=(v.get("title", "") or "").strip(),
                        price=str(v.get("price", "")).strip(),
                        available=bool(v.get("available")),
                        sku=(v.get("sku", "") or "").strip(),
                        compare_at_price=str(v.get("compare_at_price") or "").strip(),
                    )
                    for v in p.get("variants", [])
                ],
            )
            products.append(prod)
    return products


def currency(base_url: str, *, timeout: int = 15) -> str:
    """Storefront currency via the keyless /cart.js endpoint. On failure falls back to a TLD
    guess suffixed '?' so an ASSUMED currency is never displayed as a verified one."""
    base = base_url.rstrip("/")
    try:
        data = json.loads(_get(f"{base}/cart.js", timeout))
        cur = str(data.get("currency", "")).strip().upper()
        if len(cur) == 3:
            return cur
    except Exception:  # noqa: BLE001 - fall through to the guess
        pass
    if base.lower().endswith(".ca"):
        return "CAD?"
    if base.lower().endswith(".com.au"):
        return "AUD?"
    return "?"


def search(products: list[Product], keywords: list[str]) -> list[Product]:
    """Filter to products whose title/vendor matches ANY keyword (all words in the keyword present)."""
    out = []
    for p in products:
        hay = f"{p.title} {p.vendor}".lower()
        for kw in keywords:
            if all(w in hay for w in kw.lower().split()):
                out.append(p)
                break
    return out
