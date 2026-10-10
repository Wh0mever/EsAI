"""Двенадцать сценариев карусели первого экрана — что снимает vstudio_shoot_showcase.

Клиент попросил: в карусели только видео, каждый ролик показывает свой способ
применения студии, без текста и водяных знаков. Здесь — содержание этих
роликов; сама команда про него ничего не знает и берёт всё отсюда.

Ключ сценария — значение ShowcaseItem.category, порядок списка — порядок
карусели (sort = 10 × место). Тот же список ключей держат models.ShowcaseItem
и фронт (home/scenarios.ts): меняя его здесь, меняйте и там.

models — куски названий моделей студии по убыванию желания, без учёта регистра.
Берётся первая, что включена в студии и открыта аккаунту; не нашлась ни одна —
модель студии по умолчанию. «Veo 3.1» не совпадёт с «Veo 3.1 Lite» или «Fast»:
облегчённую версию нужно назвать прямо.

Запросы написаны по-английски (так их точнее понимают все модели списка) и
кончаются запретом на текст и логотипы — править их стоит только вместе с этим
хвостом.
"""
from __future__ import annotations

from dataclasses import dataclass, field

KIND_VIDEO = "video"
MODE_T2V = "t2v"
MODE_I2V = "i2v"

# Короткий ролик в обычном качестве: карусель крутит лёгкую копию 480 px,
# а 1080p стоил бы в разы дороже без видимой разницы.
DURATION = 5
RESOLUTION = "720p"
ASPECT = "16:9"
ASPECT_VERTICAL = "9:16"


def _params(aspect_ratio: str = ASPECT) -> dict:
    return {"duration": DURATION, "resolution": RESOLUTION, "aspect_ratio": aspect_ratio}


@dataclass(frozen=True)
class Scenario:
    """Один ролик карусели: что снять, на чём и с какими параметрами."""

    key: str
    title: str
    prompt: str
    models: tuple[str, ...]
    kind: str = KIND_VIDEO
    mode: str = MODE_T2V
    params: dict = field(default_factory=_params, hash=False)
    # Только для Image → Video: исходная картинка снимается первой и идёт в
    # ролик первым кадром. Модель картинки — самая дешёвая из подходящих.
    image_prompt: str = ""
    image_models: tuple[str, ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="film",
        title="Киносцена",
        models=("Veo 3.1", "Seedance 2.5", "Seedance 2.0"),
        prompt=(
            "Cinematic night scene. A detective in a long dark coat walks down a narrow "
            "rain-soaked alley glowing with teal and amber neon light, steam rising from the "
            "grates, reflections shimmering on the wet asphalt. Slow dolly-in from behind, then he "
            "glances over his shoulder. Anamorphic lens, shallow depth of field, 35mm film grain, "
            "moody and quiet. No signs, no lettering, no text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="ad",
        title="Реклама товара",
        models=("Seedance 2.0",),
        prompt=(
            "Premium product commercial. A matte black perfume bottle with a gold cap stands on "
            "wet dark stone; the camera makes a slow half orbit while a thin ribbon of water rises "
            "around it in slow motion. Soft rim light, golden reflections, macro detail, black "
            "background, studio lighting. Unbranded bottle with a blank surface. No text, no "
            "labels, no logos, no watermark."
        ),
    ),
    Scenario(
        key="person",
        title="Персонаж",
        models=("Kling", "Seedance 2.0"),
        prompt=(
            "Close-up portrait of a young woman with freckles and wind-blown dark hair on a "
            "rooftop at dusk, city lights in soft bokeh behind her. She turns to the camera and "
            "smiles slightly. Handheld 85mm, shallow depth of field, natural skin texture, warm "
            "rim light. Photorealistic. No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="car",
        title="Автомобиль",
        models=("Seedance 2.0",),
        prompt=(
            "A dark graphite concept sports coupe of an original fictional design drives fast "
            "along a winding mountain road at sunrise. Low tracking shot from the front "
            "three-quarter, wet asphalt reflections, motion blur on the wheels, mist in the valley "
            "below, cinematic colour grade. Smooth hood and grille with no emblem and no badges, "
            "blank licence plate. No text, no logos, no watermark."
        ),
    ),
    Scenario(
        key="action",
        title="Экшен",
        models=("Kling", "Seedance 2.5", "Seedance 2.0"),
        prompt=(
            "Action scene. A parkour runner sprints across city rooftops and leaps over a gap "
            "between two buildings; the camera follows from behind and swoops under him mid-jump "
            "as dust and pigeons scatter. Dynamic FPV drone shot, late afternoon sun, crisp fast "
            "motion. No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="scifi",
        title="Фантастика",
        models=("Seedance 2.5", "Veo 3.1 Lite", "Seedance 2.0"),
        prompt=(
            "Science fiction. An astronaut in a white suit walks across a red desert toward a "
            "colossal ringed planet rising over the horizon, a small rover rolling beside her, "
            "thin dust swirling in the wind. Slow tracking shot, volumetric light, vast scale, "
            "photorealistic, 65mm. No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="fashion",
        title="Fashion",
        models=("Seedance 2.5", "Seedance 2.0"),
        prompt=(
            "High-fashion editorial. A model in a flowing emerald silk dress walks toward the "
            "camera across white salt flats, the fabric billowing in strong wind, slow motion. "
            "Low angle, 50mm, soft overcast light, clean minimal composition. No text, no "
            "captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="music",
        title="Музыкальный клип",
        models=("Seedance 2.0",),
        prompt=(
            "Music video. A singer in a silver jacket performs under pulsing magenta and blue "
            "stage lights, smoke haze and lens flares around her; the camera circles her quickly "
            "and pushes in to a close-up. Handheld energy, anamorphic bokeh, concert atmosphere. "
            "No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="i2v",
        title="Image → Video",
        mode=MODE_I2V,
        models=("Seedance 2.0",),
        image_models=("FLUX", "Klein"),
        image_prompt=(
            "Photograph of a white yurt on a green alpine meadow beside a mountain lake at "
            "sunrise, a horse grazing nearby, snow peaks behind, thin smoke rising from the "
            "chimney. 35mm, natural colours, photorealistic. No text, no logos, no watermark."
        ),
        prompt=(
            "The photo comes alive: smoke drifts from the yurt, clouds move over the peaks, the "
            "grass sways in the wind and the horse lifts its head. Slow gentle push-in. Keep the "
            "composition of the image. No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="anim",
        title="Анимация",
        models=("Hailuo", "Wan", "Seedance 2.0"),
        prompt=(
            "Hand-drawn 2D anime style. A girl with a red scarf rides a bicycle along a seaside "
            "road at sunset, wind in her hair, seagulls overhead, sparkling water and towering "
            "painterly clouds. Smooth side tracking shot, vivid colours, soft cel shading. No "
            "text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="real",
        title="Реалистичная сцена",
        models=("Veo 3.1 Lite", "Seedance 2.0"),
        prompt=(
            "Documentary realism. An elderly baker pulls fresh round flatbread from a clay tandoor "
            "oven in a small morning bakery, flour dust floating in sunbeams, steam rising from "
            "the bread; close on his hands, then his smiling face. Handheld, natural light, "
            "true-to-life colours, photorealistic. No text, no captions, no logos, no watermark."
        ),
    ),
    Scenario(
        key="vertical",
        title="Reels / TikTok",
        models=("Seedance 2.0",),
        params=_params(ASPECT_VERTICAL),
        prompt=(
            "Vertical video for social media. A barista pours a layered iced matcha latte into a "
            "tall glass in close-up, then the camera whips up to her cheerful face as she slides "
            "the drink toward the lens. Bright daylight cafe, punchy colours, fast energetic "
            "movement. No text, no captions, no logos, no watermark."
        ),
    ),
)

KEYS: tuple[str, ...] = tuple(s.key for s in SCENARIOS)
BY_KEY: dict[str, Scenario] = {s.key: s for s in SCENARIOS}
SORT_STEP = 10


def position(key: str) -> int:
    """Место сценария в карусели, с единицы."""
    return KEYS.index(key) + 1


def sort_for(key: str) -> int:
    """ShowcaseItem.sort сценария: шаг 10 оставляет место вставить работу между соседями."""
    return position(key) * SORT_STEP


__all__ = ["Scenario", "SCENARIOS", "KEYS", "BY_KEY", "SORT_STEP", "MODE_T2V", "MODE_I2V",
           "KIND_VIDEO", "position", "sort_for"]
