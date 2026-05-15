import json
from pathlib import Path

import pytest

from utils import food_lookup

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def test_fetch_product_success(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    assert product is not None
    assert product.name == "Tesco Wholemeal Bread"
    assert product.serving_size_g == 44.0
    assert product.kcal_per_100g == 238
    assert product.protein_per_100g == 12


def test_fetch_product_not_found(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": 0}
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    assert food_lookup.fetch_product("9999999999999") is None


def test_fetch_product_http_error(mocker):
    mocker.patch("utils.food_lookup.requests.get", side_effect=Exception("boom"))
    assert food_lookup.fetch_product("5012345678900") is None


def test_fetch_product_missing_kcal_returns_partial(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_no_kcal.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("0000000000000")
    assert product is not None
    assert product.kcal_per_100g is None
    assert product.protein_per_100g == 5


def test_compute_portion_by_grams(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    portion = food_lookup.compute_portion(product, grams=88.0, servings=None)
    # 238 * 0.88 = 209.44 -> 209.4 kcal
    assert portion["kcal"] == pytest.approx(209.4, abs=0.1)
    # 12 * 0.88 = 10.56 -> 10.6 g protein
    assert portion["protein_g"] == pytest.approx(10.6, abs=0.1)
    assert portion["fibre_g"] == pytest.approx(5.3, abs=0.1)
    assert portion["effective_grams"] == 88.0


def test_compute_portion_by_servings(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    portion = food_lookup.compute_portion(product, grams=None, servings=2.0)
    # 2 servings * 44 g/serving = 88 g => same as the grams case
    assert portion["effective_grams"] == pytest.approx(88.0)
    assert portion["kcal"] == pytest.approx(209.4, abs=0.1)


def test_compute_portion_requires_grams_or_servings(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    with pytest.raises(ValueError):
        food_lookup.compute_portion(product, grams=None, servings=None)


def test_parse_serving_size_handles_units():
    assert food_lookup._parse_serving_size_grams("44 g") == 44.0
    assert food_lookup._parse_serving_size_grams("250ml") is None   # ml ≠ g; skip
    assert food_lookup._parse_serving_size_grams("") is None
    assert food_lookup._parse_serving_size_grams(None) is None
