"""Цена ролика в боте — из таблицы сервера под разрешение, а не «секунды × тариф»."""
from bot.routers.video import _cost


def test_cost_uses_server_price_for_resolution():
    draft = {"duration": 15, "res": "1080p", "cps": 32,
             "prices": {"720p": {"15": 480}, "1080p": {"15": 1142}}}
    assert _cost(draft) == 1142
    draft["res"] = "720p"
    assert _cost(draft) == 480


def test_no_table_means_no_price():
    """Без таблицы сервера цены нет: тариф видео — не цена (у Seedance он 0)."""
    assert _cost({"duration": 5, "res": "720p", "cps": 32}) is None
    assert _cost({"duration": 5, "res": "4K", "cps": 32, "prices": {"720p": {"5": 160}}}) is None
    assert _cost({"duration": 7, "res": "720p", "prices": {"720p": {"5": 160}}}) is None
    assert _cost({"duration": 5, "res": "720p", "prices": {"720p": {"5": 0}}}) is None


def test_cost_uses_aspect_table_when_price_depends_on_it():
    draft = {"duration": 5, "res": "1080p", "ar": "21:9", "cps": 32,
             "prices": {"1080p": {"5": 382}},
             "prices_ar": {"21:9": {"1080p": {"5": 500}}, "16:9": {"1080p": {"5": 382}}}}
    assert _cost(draft) == 500
    draft["ar"] = "1:1"
    assert _cost(draft) == 382


def test_model_without_quality_choice_uses_its_only_table():
    """Качество не выбирается — сервер считает таблицу под разрешение по умолчанию."""
    assert _cost({"duration": 5, "prices": {"720p": {"5": 68, "10": 136}}}) == 68
    # Две строки и разрешение не выбрано — гадать, какую спишут, нельзя.
    assert _cost({"duration": 5, "prices": {"720p": {"5": 68}, "1080p": {"5": 99}}}) is None
