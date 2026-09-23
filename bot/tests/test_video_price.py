"""Цена ролика в боте — из таблицы сервера под разрешение, а не «секунды × тариф»."""
from bot.routers.video import _cost


def test_cost_uses_server_price_for_resolution():
    draft = {"duration": 15, "res": "1080p", "cps": 32,
             "prices": {"720p": {"15": 480}, "1080p": {"15": 1142}}}
    assert _cost(draft) == 1142
    draft["res"] = "720p"
    assert _cost(draft) == 480


def test_cost_falls_back_to_tariff_without_table():
    assert _cost({"duration": 5, "res": "720p", "cps": 32}) == 160
    assert _cost({"duration": 5, "res": "4K", "cps": 32, "prices": {"720p": {"5": 160}}}) == 160


def test_cost_uses_aspect_table_when_price_depends_on_it():
    draft = {"duration": 5, "res": "1080p", "ar": "21:9", "cps": 32,
             "prices": {"1080p": {"5": 382}},
             "prices_ar": {"21:9": {"1080p": {"5": 500}}, "16:9": {"1080p": {"5": 382}}}}
    assert _cost(draft) == 500
    draft["ar"] = "1:1"
    assert _cost(draft) == 382
