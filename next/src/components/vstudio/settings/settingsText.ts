/**
 * Видеостудия, правая панель «Параметры запуска»: русские тексты по умолчанию.
 *
 * Ключи — namespace "vstudio" (§10). Компоненты зовут t(key, {defaultValue}),
 * а defaultValue берут отсюда: так у FE-6 один источник для ru/vstudio.json,
 * и тесты видят те же строки, что и человек. Подстановки — формат i18next {{x}}.
 *
 * Модуль без импорта значений: его грузят и Next, и node-тесты.
 */
import type { TFunction } from "i18next";

export const SETTINGS_RU = {
  "kind.video": "Видео",
  "kind.image": "Картинка",
  "kind.soon": "скоро",
  "kind.label": "Что создаём",

  "settings.title": "Параметры запуска",
  "settings.hide": "Скрыть параметры",
  "settings.model": "Модель",
  "settings.modelChange": "Сменить модель",
  "settings.modelCollapse": "Свернуть список",
  "settings.modelsLoading": "Загружаем модели…",
  "settings.modelsEmpty": "Сейчас нет доступных моделей",
  "settings.modelsError": "Не удалось загрузить модели",
  "settings.retry": "Повторить",
  "settings.selected": "Выбрана",
  "settings.pickOther": "Выбрать другую модель",

  "settings.aspect": "Пропорции",
  "settings.aspectAuto": "Авто",
  "settings.aspectAutoVideo": "Модель выберет сама — по первому кадру, если он есть",
  "settings.aspectAutoImage": "Модель нарисует своим размером",
  "settings.aspectUnsupported": "{{model}} не снимает в {{value}} — выберите другую пропорцию",

  "settings.duration": "Длительность",
  "settings.seconds": "{{n}} с",
  "settings.durationForced": "С фото-референсами {{model}} снимает только {{n}} с — другие значения недоступны",
  "settings.durationUnsupported": "{{model}} не снимает {{n}} с — выберите другое значение",
  "settings.showAll": "Все значения ({{n}})",
  "settings.showLess": "Свернуть",

  "settings.resolution": "Качество",
  "settings.resolutionOnly": "{{model}} снимает только в {{res}}",
  "settings.resolutionUnsupported": "{{model}} не снимает в {{res}} — выберите другое качество",

  "settings.audio": "Звук",
  "settings.audioHint": "Модель сама озвучит ролик: речь, шумы, музыка",
  "settings.audioOff": "Ролик будет без звука",
  "settings.audioUnsupported": "{{model}} снимает без звука",

  "settings.advanced": "Дополнительно",
  "settings.advancedNone": "{{model}} не поддерживает seed и негативный промпт",
  "settings.seed": "Seed",
  "settings.seedHint": "Тот же seed с теми же настройками даёт похожий результат. Пусто — каждый раз по-новому",
  "settings.seedPlaceholder": "Случайный",
  "settings.seedRandom": "Случайное число",
  "settings.seedClear": "Очистить",
  "settings.seedInvalid": "Seed — целое число от 0 до {{max}}",
  "settings.seedUnsupported": "{{model}} не поддерживает seed",
  "settings.negative": "Негативный промпт",
  "settings.negativeHint": "Чего не должно быть в кадре",
  "settings.negativePlaceholder": "Например: размытость, текст на экране, водяные знаки",
  "settings.negativeCount": "{{n}} / {{max}}",
  "settings.negativeUnsupported": "{{model}} не принимает негативный промпт",

  "settings.priceFrom": "от {{n}} кр",
  "settings.perImage": "{{n}} кр за картинку",
  "settings.credits": "{{n}} кр",
  "settings.locked": "Доступно на платном тарифе",
  "settings.eta": "обычно {{t}}",
  "settings.etaSec": "~{{n}} с",
  "settings.etaMin": "~{{n}} мин",
  "settings.disabledWhy": "Недоступно: {{reason}}",

  "settings.badge.refs": "до {{n}} фото",
  "settings.badge.frames": "первый и последний кадр",
  "settings.badge.firstFrame": "первый кадр",
  "settings.badge.audio": "звук",
  "settings.badge.duration": "до {{n}} с",
  "settings.badge.resolution": "до {{res}}",

  "settings.compat.refsOff": "Не работает с фото-референсами — у вас {{n}}",
  "settings.compat.tooManyRefs": "Принимает не больше {{max}} фото, у вас {{n}}",
  "settings.compat.noFrames": "Не умеет начинать видео с кадра",
  "settings.compat.noLastFrame": "Не умеет заканчивать видео кадром",
  "settings.compat.framesRefs": "Кадры и фото-референсы вместе не использует",
  "settings.compat.forced": "С фото-референсами — только {{n}} с",
  "settings.compat.imageFrames": "Кадры картинке не нужны",

  "settings.howRefsUsed": "Как модель использует ваши фото",
  "settings.refRole": "{{label}} — {{role}}",
  "settings.refNoRole": "роль не указана — модель решит сама",
  "settings.roleHint": "Подпишите в лотке, кто или что на фото («героиня», «кухня») — модель поймёт точнее.",
  "settings.refOverflow": "лишнее: {{model}} принимает до {{max}} фото",
  "settings.frameFirst": "видео начнётся с этого кадра",
  "settings.frameLast": "видео закончится этим кадром",
  "settings.framePinned": "уйдёт как Image {{k}}: начало будет похожим, но не точь-в-точь",
  "settings.frameImage": "для картинки кадры не используются",
  "settings.refExcluded": "не учитывается и не оплачивается",
  "settings.refUploading": "загружается…",
  "settings.refFailed": "не загрузилось",
  "settings.refPending": "ещё создаётся…",
  "settings.refDeleted": "удалено",
  "settings.refIgnored": "{{model}} не использует фото-референсы",

  "settings.mode.t2v": "Без фото: модель снимет только по тексту. Добавьте фото через @ или «+» — как героя или как первый кадр.",
  "settings.mode.i2v": "Видео начнётся с первого кадра, дальше — по тексту.",
  "settings.mode.flf2v": "Видео начнётся с первого кадра и закончится последним.",
  "settings.mode.lf": "Видео закончится последним кадром.",
  "settings.mode.r2v": "Фото-референсы: модель возьмёт из них героев, предметы и места. @Image N в тексте — это фото N.",
  "settings.mode.r2v_pin": "Фото-референсы и первый кадр: кадр уйдёт как Image {{k}}, начало будет похожим, но не точь-в-точь.",
  "settings.mode.t2i": "Без фото: модель нарисует только по тексту.",
  "settings.mode.i2i": "Модель опирается на ваши фото: @Image N в тексте — это фото N.",
  "settings.mode.conflict": "{{model}} не может одновременно использовать кадры и фото-референсы — выберите что-то одно.",
  "settings.mode.refsOff": "{{model}} не умеет работать с фото-референсами. Сделайте фото первым кадром или выберите другую модель.",

  "settings.fact.maxRefs": "до {{n}} фото",
  "settings.fact.minPx": "фото от {{n}} px",
  "settings.fact.faces": "без фото реальных людей",
  "settings.fact.en": "лучше понимает английский",

  "settings.priceHint": "Цены под значениями — без фото-референсов. Точная сумма — на кнопке «Создать».",
  "settings.exact": "Оценка точная: столько и спишется, только если результат получится.",
  "settings.chipAria": "Параметры запуска: {{summary}}",

  "mobile.params": "Параметры",
  "mobile.close": "Закрыть",
} as const;

export type SettingsTextKey = keyof typeof SETTINGS_RU;

/** Ключ и подстановки без перевода: чистая логика отдаёт их, компонент переводит. */
export type TextRef = { key: SettingsTextKey; params?: Record<string, string | number> };

/** t из useTranslation("vstudio") или простая функция (тесты). */
export type Translate = TFunction | ((key: string, options?: Record<string, unknown>) => unknown);

/** Подставить {{x}} в русский шаблон — для тестов и мест без i18next. */
export function fillText(template: string, params?: Record<string, string | number>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) =>
    params && name in params ? String(params[name]) : "",
  );
}

/** Перевод ключа панели: ns vstudio, русский из SETTINGS_RU — defaultValue. */
export function tx(t: Translate, key: SettingsTextKey, params?: Record<string, string | number>): string {
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(key, { ns: "vstudio", defaultValue: SETTINGS_RU[key], ...(params || {}) });
  return typeof out === "string" ? out : fillText(SETTINGS_RU[key], params);
}

/** То же для TextRef из чистой логики. */
export function txRef(t: Translate, ref: TextRef): string {
  return tx(t, ref.key, ref.params);
}

/** «1 200» — кредиты с неразрывным разделителем тысяч, как в PaywallModal. */
export function fmtNum(n: number): string {
  return Math.round(n).toLocaleString("ru-RU");
}
