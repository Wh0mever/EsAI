"""Спеки каталога OpenRouter /videos/models и модели-заглушки для тестов caps и компилятора.

Значения — по живому каталогу и документации вендоров на 24.09.2026 (см. исследование
провайдеров). Сеть в тестах не трогаем: спеку передаём напрямую.
"""
from types import SimpleNamespace

from vstudio import caps as caps_mod

SEEDANCE_20 = {
    "id": "bytedance/seedance-2.0",
    "supported_durations": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "supported_resolutions": ["480p", "720p", "1080p", "4K"],
    "supported_aspect_ratios": ["1:1", "3:4", "9:16", "4:3", "16:9", "21:9", "9:21"],
    "generate_audio": True,
    "seed": True,
    "allowed_passthrough_parameters": ["watermark", "req_key"],
    "pricing_skus": {"video_tokens": "0.000007"},
}
SEEDANCE_MINI = dict(SEEDANCE_20, id="bytedance/seedance-2.0-mini",
                     supported_resolutions=["480p", "720p"])
VEO_FAST = {
    "id": "google/veo-3.1-fast",
    "supported_durations": [4, 6, 8],
    "supported_resolutions": ["720p", "1080p", "4K"],
    "supported_aspect_ratios": ["16:9", "9:16"],
    "generate_audio": True,
    "seed": True,
    "allowed_passthrough_parameters": ["personGeneration", "aspectRatio", "negativePrompt",
                                       "conditioningScale", "enhancePrompt"],
}
KLING_STD = {
    "id": "kwaivgi/kling-v3.0-std",
    "supported_durations": list(range(3, 16)),
    "supported_resolutions": ["720p"],
    "supported_aspect_ratios": ["16:9", "9:16", "1:1"],
    "generate_audio": True,
    "seed": False,
    "allowed_passthrough_parameters": ["negative_prompt", "cfg_scale"],
}
HAILUO_23 = {
    "id": "minimax/hailuo-2.3",
    "supported_durations": [6, 10],
    "supported_resolutions": ["1080p"],
    "supported_aspect_ratios": ["16:9"],
    "generate_audio": False,
}
HAILUO_3 = {
    "id": "minimax/hailuo-3",
    "supported_durations": list(range(5, 16)),
    "supported_resolutions": ["2K"],
    "supported_aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
    "generate_audio": True,
}
WAN_27 = {
    "id": "alibaba/wan-2.7",
    "supported_durations": list(range(2, 11)),
    "supported_resolutions": ["720p", "1080p"],
    "supported_aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "generate_audio": True,
    "seed": True,
    "allowed_passthrough_parameters": ["negative_prompt", "prompt_extend"],
}
GROK = {
    "id": "x-ai/grok-imagine-video",
    "supported_durations": list(range(1, 16)),
    "supported_resolutions": ["480p", "720p"],
    "supported_aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
    "generate_audio": None,
}

SPECS = {s["id"]: s for s in (SEEDANCE_20, SEEDANCE_MINI, VEO_FAST, KLING_STD, HAILUO_23,
                              HAILUO_3, WAN_27, GROK)}

NAMES = {
    "bytedance/seedance-2.0": "Seedance 2.0",
    "bytedance/seedance-2.0-mini": "Seedance 2.0 mini",
    "google/veo-3.1-fast": "Veo 3.1 Fast",
    "kwaivgi/kling-v3.0-std": "Kling v3 std",
    "minimax/hailuo-2.3": "Hailuo 2.3",
    "minimax/hailuo-3": "Hailuo 3",
    "alibaba/wan-2.7": "Wan 2.7",
    "x-ai/grok-imagine-video": "Grok Imagine",
    "google/gemini-2.5-flash-image": "Nano Banana",
    "google/gemini-3.1-flash-image-preview": "Nano Banana 2",
    "black-forest-labs/flux.2-flex": "FLUX.2 flex",
}


def model(openrouter_id: str, **kw):
    """Заглушка GPTModels с теми же именами полей (без БД)."""
    data = {
        "openrouter_id": openrouter_id,
        "name": NAMES.get(openrouter_id, openrouter_id),
        "short_label": "",
        "sort_order": 100,
        "is_active": True,
        "vstudio_enabled": True,
        "vstudio_overrides": {},
        "markup_coefficient": 32,
    }
    data.update(kw)
    return SimpleNamespace(**data)


def make_caps(openrouter_id: str, overrides: dict | None = None, spec: dict | None = None):
    """Caps модели по спеке из SPECS (или переданной)."""
    m = model(openrouter_id, vstudio_overrides=overrides or {})
    if spec is None:
        spec = SPECS.get(openrouter_id)
    got = caps_mod.for_model(m, spec=spec)
    assert got is not None, f"caps для {openrouter_id} не собрались"
    return got
