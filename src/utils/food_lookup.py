"""Open Food Facts client + portion-based nutrition computation."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_TIMEOUT_S = 5.0
_NUTRIENTS_PER_100G = ("kcal", "protein", "carbs", "fat", "fibre", "sugar")


@dataclass
class OffProduct:
    barcode: str
    name: str
    serving_size_g: Optional[float]
    kcal_per_100g: Optional[float]
    protein_per_100g: Optional[float]
    carbs_per_100g: Optional[float]
    fat_per_100g: Optional[float]
    fibre_per_100g: Optional[float]
    sugar_per_100g: Optional[float]
    image_url: Optional[str]


def fetch_product(barcode: str) -> Optional[OffProduct]:
    """Look up a product by barcode on Open Food Facts.

    Returns ``None`` if the product isn't in OFF or the request fails.
    Missing nutrients are returned as ``None`` on the product (caller is
    expected to fall back to manual entry for those fields).
    """
    try:
        resp = requests.get(_OFF_URL.format(barcode=barcode), timeout=_TIMEOUT_S)
    except Exception:
        logger.warning("OFF lookup failed for %s", barcode, exc_info=True)
        return None

    if resp.status_code != 200:
        return None

    payload = resp.json()
    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    nutriments = product.get("nutriments") or {}

    def _num(key: str) -> Optional[float]:
        value = nutriments.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return OffProduct(
        barcode=barcode,
        name=product.get("product_name") or "Unknown product",
        serving_size_g=_parse_serving_size_grams(product.get("serving_size")),
        kcal_per_100g=_num("energy-kcal_100g"),
        protein_per_100g=_num("proteins_100g"),
        carbs_per_100g=_num("carbohydrates_100g"),
        fat_per_100g=_num("fat_100g"),
        fibre_per_100g=_num("fiber_100g"),
        sugar_per_100g=_num("sugars_100g"),
        image_url=product.get("image_small_url"),
    )


def compute_portion(
    product: OffProduct,
    *,
    grams: Optional[float],
    servings: Optional[float],
) -> dict:
    """Compute absolute nutrition for a portion of an OFF product.

    Exactly one of ``grams`` or ``servings`` must be provided. ``servings``
    requires the product to have a parsable ``serving_size_g``.
    """
    if grams is None and servings is None:
        raise ValueError("Provide either grams or servings")
    if grams is not None and servings is not None:
        raise ValueError("Provide grams OR servings, not both")
    if grams is not None and grams <= 0:
        raise ValueError("grams must be positive")
    if servings is not None and servings <= 0:
        raise ValueError("servings must be positive")
    if product.kcal_per_100g is None:
        raise ValueError(
            "Product has no kcal data; use manual entry instead"
        )

    if servings is not None:
        if product.serving_size_g is None:
            raise ValueError("Product has no serving size; use grams")
        effective_grams = float(servings) * product.serving_size_g
    else:
        effective_grams = float(grams)

    scale = effective_grams / 100.0

    def _scaled(per_100g: Optional[float]) -> Optional[float]:
        if per_100g is None:
            return None
        return round(per_100g * scale, 1)

    return {
        "effective_grams": round(effective_grams, 2),
        "kcal": _scaled(product.kcal_per_100g),
        "protein_g": _scaled(product.protein_per_100g),
        "carbs_g": _scaled(product.carbs_per_100g),
        "fat_g": _scaled(product.fat_per_100g),
        "fibre_g": _scaled(product.fibre_per_100g),
        "sugar_g": _scaled(product.sugar_per_100g),
    }


_SERVING_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*g\b", re.IGNORECASE)


def _parse_serving_size_grams(raw) -> Optional[float]:
    """Parse Open Food Facts' free-form ``serving_size`` (e.g. ``"44 g"``).

    Only accepts gram-denominated sizes; returns ``None`` for ``ml`` etc.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = _SERVING_RE.match(raw)
    return float(match.group(1)) if match else None
