/**
 * Лента видеостудии: чистая логика без React и без сети.
 *
 * Всё, что можно посчитать из ShotJSON/TakeLite, считается здесь, а
 * компоненты только переводят и рисуют. Так правила (какой вход «не учтён»,
 * когда «дольше обычного», какой дубль показывать) проверяет node-тест
 * feedLogic.test.mjs, а не глаз на стенде.
 */
import { OPEN_TAKE_STATUSES } from "@/lib/vstudio/types";
import type {
  AssetJSON,
  DroppedInput,
  InputSlot,
  ModelJSON,
  ShotInputJSON,
  ShotJSON,
  TakeLite,
  TakeMode,
  TakeStatus,
  Uid,
  VsKind,
} from "@/lib/vstudio/types";

/** Кадров на страницу ленты (GET projects/<uid>/shots/?limit=). */
export const FEED_PAGE_SIZE = 20;
/** «Дольше обычного» — после 1.5×ETA (§9.6). */
export const SLOW_FACTOR = 1.5;
/** Насколько близко к низу ленты человек «внизу» и его можно докрутить к новому. */
export const NEAR_BOTTOM_PX = 160;
/** Лента «стоит на самом низу» и едет вместе с панелью запроса; запас — на дробные пиксели прокрутки. */
export const PINNED_BOTTOM_PX = 8;

/* ------------------------------------------------------------------ */
/* Дубли                                                               */
/* ------------------------------------------------------------------ */

export function isOpenStatus(status: TakeStatus): boolean {
  return OPEN_TAKE_STATUSES.includes(status);
}

/** Режимы, в которых модели уходят фото: отправка тогда дольше («до 2 мин»). */
const IMAGE_MODES: readonly TakeMode[] = ["i2v", "flf2v", "r2v", "r2v_pin", "i2i"];

export function modeSendsImages(mode: TakeMode | null | undefined): boolean {
  return Boolean(mode && IMAGE_MODES.includes(mode));
}

/** uid открытых дублей (их и опрашиваем) — по порядку, без повторов. */
export function openTakeUids(takes: Iterable<TakeLite>): Uid[] {
  const out = new Set<Uid>();
  for (const t of takes) if (isOpenStatus(t.status)) out.add(t.uid);
  return [...out].sort();
}

const time = (iso: string | null | undefined): number => {
  const v = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(v) ? v : 0;
};

/** По возрастанию created_at; при равенстве — по uid, чтобы порядок не прыгал. */
export function compareTakes(a: TakeLite, b: TakeLite): number {
  const d = time(a.created_at) - time(b.created_at);
  if (d) return d;
  return a.uid < b.uid ? -1 : a.uid > b.uid ? 1 : 0;
}

/** Дубли из стора, сгруппированные по кадру (take.shot). */
export function indexTakesByShot(takes: Iterable<TakeLite>): Map<Uid, TakeLite[]> {
  const out = new Map<Uid, TakeLite[]>();
  for (const t of takes) {
    const list = out.get(t.shot);
    if (list) list.push(t);
    else out.set(t.shot, [t]);
  }
  return out;
}

/**
 * Дубли кадра: то, что пришло с кадром (shot.takes), плюс свежее из стора
 * (опрос, «Повторить»). Запись стора новее — она и побеждает.
 */
export function shotTakes(shot: Pick<ShotJSON, "uid" | "takes">, fromStore?: readonly TakeLite[] | null): TakeLite[] {
  const byUid = new Map<Uid, TakeLite>();
  for (const t of shot.takes || []) byUid.set(t.uid, t);
  for (const t of fromStore || []) if (t.shot === shot.uid) byUid.set(t.uid, t);
  return [...byUid.values()].sort(compareTakes);
}

/** Поэлементное равенство списков: memo карточки не перерисует её без причины. */
export function sameItems<T>(a: readonly T[], b: readonly T[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Какой дубль показать: выбранный человеком (если он ещё есть), иначе
 * последний — новый дубль после «Повторить» сразу на виду.
 */
export function pickTakeIndex(takes: readonly TakeLite[], selected: Uid | null): number {
  if (!takes.length) return -1;
  if (selected) {
    const i = takes.findIndex((t) => t.uid === selected);
    if (i >= 0) return i;
  }
  return takes.length - 1;
}

/**
 * «Повторить» только у завершённых дублей (§9.6): иначе можно заплатить
 * дважды за ещё идущий. model === null — каталог загружен, а модели в нём
 * больше нет; undefined — каталог ещё не пришёл, не блокируем.
 */
export function retryBlock(
  shot: Pick<ShotJSON, "model">,
  takes: readonly TakeLite[],
  model: ModelJSON | null | undefined,
): null | "open" | "model" {
  if (takes.some((t) => isOpenStatus(t.status))) return "open";
  if (!shot.model || model === null) return "model";
  return null;
}

/** Модель кадра в каталоге: undefined — каталог ещё не загружен, null — модели нет. */
export function findModel(
  models: { video: ModelJSON[]; image: ModelJSON[] } | null | undefined,
  kind: VsKind,
  id: string | null | undefined,
): ModelJSON | null | undefined {
  if (!models) return undefined;
  if (!id) return null;
  return (kind === "image" ? models.image : models.video).find((m) => m.id === id) ?? null;
}

/* ------------------------------------------------------------------ */
/* Статус и время                                                      */
/* ------------------------------------------------------------------ */

export type Phrase = { key: string; ru: string; params?: Record<string, string | number> };

/** Подпись статуса дубля (§9.6): ключ vstudio и русский по умолчанию. */
export function statusPhrase(take: Pick<TakeLite, "status" | "kind" | "mode" | "queue_position">): Phrase {
  switch (take.status) {
    case "queued": {
      const pos = take.queue_position;
      // 0 — следующий в очереди; «вы N-й» — только когда перед вами кто-то есть.
      if (typeof pos === "number" && pos > 0) {
        return { key: "run.status.queuedPos", ru: "В очереди · вы {{n}}-й", params: { n: pos + 1 } };
      }
      return { key: "run.status.queued", ru: "В очереди" };
    }
    case "submitting":
      return modeSendsImages(take.mode)
        ? { key: "run.status.submittingRefs", ru: "Отправляем модели… с фото это до 2 мин" }
        : { key: "run.status.submitting", ru: "Отправляем модели…" };
    case "running":
      return take.kind === "image"
        ? { key: "run.status.runningImage", ru: "Рисуем картинку" }
        : { key: "run.status.running", ru: "Снимается" };
    case "saving":
      return { key: "run.status.saving", ru: "Сохраняем…" };
    case "done":
      return take.kind === "image"
        ? { key: "run.status.doneImage", ru: "Картинка готова" }
        : { key: "run.status.done", ru: "Видео готово" };
    case "failed":
      return { key: "run.status.failed", ru: "Не получилось" };
    case "canceled":
      return { key: "run.status.canceled", ru: "Отменено" };
    case "lost":
      // Только итог: причин у lost несколько, её называет takeErrorText по error.code.
      return { key: "run.status.lost", ru: "Не выдано" };
    default:
      return { key: "run.status.queued", ru: "В очереди" };
  }
}

/** 7 → «0:07», 84 → «1:24», 3723 → «1:02:03». */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(Number.isFinite(totalSeconds) ? totalSeconds : 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** ETA словами: до минуты — секунды (кратно 5), дальше — целые минуты. null — оценки нет. */
export function etaPhrase(seconds: number | null | undefined): Phrase | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) {
    return { key: "run.time.sec", ru: "{{n}} с", params: { n: Math.max(5, Math.round(seconds / 5) * 5) } };
  }
  return { key: "run.time.min", ru: "{{n}} мин", params: { n: Math.max(1, Math.round(seconds / 60)) } };
}

/** «Дольше обычного — можно закрыть вкладку» после 1.5×ETA. */
export function isSlow(elapsed: number, eta: number | null | undefined): boolean {
  return typeof eta === "number" && eta > 0 && elapsed > eta * SLOW_FACTOR;
}

/**
 * Доля полосы прогресса. Честного прогресса провайдер не даёт, поэтому
 * полоса идёт по ETA до 90 % и дальше только подползает — никогда не 100 %,
 * пока дубль не закрыт.
 */
export function progressShare(elapsed: number, eta: number | null | undefined): number | null {
  if (typeof eta !== "number" || !Number.isFinite(eta) || eta <= 0) return null;
  const e = Math.max(0, elapsed);
  if (e <= eta) return 0.9 * (e / eta);
  return Math.min(0.98, 0.9 + 0.08 * (1 - eta / e));
}

/** Секунды дубля с опорой на серверный elapsed_s (часы телефона могут врать). */
export function liveElapsed(serverElapsed: number, anchorAtMs: number, nowMs: number): number {
  const base = Number.isFinite(serverElapsed) ? Math.max(0, serverElapsed) : 0;
  if (!anchorAtMs || !nowMs || nowMs < anchorAtMs) return base;
  return base + (nowMs - anchorAtMs) / 1000;
}

/** Всплывающее сообщение о закрытии дубля; null — молчим (отмену человек сделал сам). */
export function settledToast(
  take: Pick<TakeLite, "uid" | "status" | "kind">,
): { id: string; tone: "ok" | "error"; phrase: Phrase } | null {
  if (take.status === "done") {
    return {
      id: `vs-take-${take.uid}-done`,
      tone: "ok",
      phrase:
        take.kind === "image"
          ? { key: "toast.imageDone", ru: "Картинка готова" }
          : { key: "toast.videoDone", ru: "Видео готово" },
    };
  }
  if (take.status === "failed") {
    return {
      id: `vs-take-${take.uid}-failed`,
      tone: "error",
      phrase: { key: "toast.failed", ru: "Не получилось — кредиты не списаны" },
    };
  }
  if (take.status === "lost") {
    // «Не получилось» тут бывает неправдой: ролик мог быть снят и ждёт довоза.
    return {
      id: `vs-take-${take.uid}-lost`,
      tone: "error",
      phrase: { key: "toast.lost", ru: "Не выдано — кредиты не списаны, проверим вручную" },
    };
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Промпт с чипами                                                     */
/* ------------------------------------------------------------------ */

export type RefState = "ok" | "excluded" | "missing";

export type PromptSegment =
  | { kind: "text"; text: string }
  | {
      kind: "ref";
      asset: Uid;
      /** "Image 1" | "first_frame" | "last_frame" | null (не ушло модели). */
      label: string | null;
      n: number | null;
      slot: InputSlot | null;
      state: RefState;
      role: string;
      thumb: string | null;
    };

const IMAGE_LABEL = /^Image\s+(\d+)$/;

/** «Image 3» → 3; всё остальное → null. */
export function labelNumber(label: string | null | undefined): number | null {
  const m = label ? IMAGE_LABEL.exec(label.trim()) : null;
  return m ? Number(m[1]) : null;
}

/**
 * prompt_doc кадра → абзацы из текста и чипов. Метку чипа берём из
 * inputs[].label (её посчитал сервер при запуске), а не из текущего лотка:
 * карточка показывает то, что было, даже если лоток уже другой.
 */
export function promptSegments(shot: Pick<ShotJSON, "prompt_doc" | "prompt_text" | "inputs">): PromptSegment[][] {
  const byAsset = new Map<Uid, ShotInputJSON>();
  for (const i of shot.inputs || []) if (!byAsset.has(i.asset.uid)) byAsset.set(i.asset.uid, i);
  const blocks = Array.isArray(shot.prompt_doc?.blocks) ? shot.prompt_doc.blocks : [];
  const out: PromptSegment[][] = blocks.map((block) =>
    (Array.isArray(block) ? block : []).flatMap((node): PromptSegment[] => {
      if (!node || typeof node !== "object") return [];
      if (node.t === "text") return node.v ? [{ kind: "text", text: node.v }] : [];
      if (node.t !== "ref") return [];
      const input = byAsset.get(node.asset);
      if (!input) {
        return [{ kind: "ref", asset: node.asset, label: null, n: null, slot: null, state: "missing", role: "", thumb: null }];
      }
      const off = !input.included || !input.label;
      return [
        {
          kind: "ref",
          asset: node.asset,
          label: input.label,
          n: off ? null : labelNumber(input.label),
          slot: input.slot,
          state: off ? "excluded" : "ok",
          role: input.role || "",
          thumb: input.asset.thumb_url || input.asset.url || null,
        },
      ];
    }),
  );
  const empty = out.every((b) => b.length === 0);
  if (empty && shot.prompt_text) return [[{ kind: "text", text: shot.prompt_text }]];
  return out;
}

/** Длинный промпт показываем свёрнутым с кнопкой «Показать полностью» (но никогда не режем). */
export function isLongPrompt(text: string | null | undefined): boolean {
  if (!text) return false;
  return text.length > 320 || text.split("\n").length > 5;
}

/* ------------------------------------------------------------------ */
/* Входы кадра («не учтено», виноватый вход)                           */
/* ------------------------------------------------------------------ */

export type InputRow = {
  key: string;
  input: ShotInputJSON;
  /** Номер @Image N у ушедшего референса. */
  n: number | null;
  /** Не ушло модели: выключено человеком или отброшено компилятором. */
  excluded: boolean;
  /** excluded_by_user | duplicate_frame | … ; null — ушло модели. */
  reason: string | null;
  /** Из-за этого входа модель отказала (TakeLite.error.input). */
  culprit: boolean;
};

const SLOT_ORDER: Record<InputSlot, number> = { reference: 0, first_frame: 1, last_frame: 2 };

export function inputRows(
  inputs: readonly ShotInputJSON[] | null | undefined,
  dropped: readonly DroppedInput[] | null | undefined,
  culprit: Uid | null | undefined,
): InputRow[] {
  const drop = new Map<string, string>();
  for (const d of dropped || []) drop.set(`${d.slot}:${d.asset}`, String(d.reason || "excluded_by_user"));
  return [...(inputs || [])]
    .sort((a, b) => SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot] || a.position - b.position)
    .map((input) => {
      const dropReason = drop.get(`${input.slot}:${input.asset.uid}`) ?? null;
      const excluded = !input.included || !input.label || dropReason !== null;
      return {
        key: `${input.slot}:${input.asset.uid}`,
        input,
        n: excluded ? null : labelNumber(input.label),
        excluded,
        reason: excluded ? dropReason ?? "excluded_by_user" : null,
        culprit: Boolean(culprit && input.asset.uid === culprit),
      };
    });
}

/* ------------------------------------------------------------------ */
/* Сводка параметров «Seedance 2.0 · 9:16 · 10 с · 720p»               */
/* ------------------------------------------------------------------ */

export type ParamsSummary = {
  model: string | null;
  aspect: string | null;
  duration: number | null;
  resolution: string | null;
  /** null — модель без звука или картинка. */
  audio: boolean | null;
};

/** Итог дубля (effective) важнее запрошенного: Veo с референсами снимает 8 с, а не 5. */
export function paramsSummary(
  shot: Pick<ShotJSON, "kind" | "model" | "params">,
  take?: Pick<TakeLite, "effective"> | null,
): ParamsSummary {
  const eff = take?.effective || {};
  const req = shot.params || {};
  const pick = <T,>(a: T | undefined, b: T | undefined): T | null => (a !== undefined && a !== null ? a : b ?? null);
  const video = shot.kind === "video";
  const audio = video ? pick(eff.generate_audio, req.generate_audio) : null;
  return {
    model: shot.model?.name || null,
    aspect: pick(eff.aspect_ratio, req.aspect_ratio),
    duration: video ? pick(eff.duration, req.duration) : null,
    resolution: video ? pick(eff.resolution, req.resolution) : null,
    audio: typeof audio === "boolean" ? audio : null,
  };
}

/* ------------------------------------------------------------------ */
/* Результат                                                           */
/* ------------------------------------------------------------------ */

/** "9:16" → 0.5625; мусор → null. */
export function parseAspect(value: string | null | undefined): number | null {
  const m = value ? /^(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)$/.exec(value.trim()) : null;
  if (!m) return null;
  const w = Number(m[1]);
  const h = Number(m[2]);
  return w > 0 && h > 0 ? w / h : null;
}

/** Ширина/высота кадра для рамки: размеры файла, иначе пропорция запуска, иначе 16:9. */
export function mediaRatio(
  asset: Pick<AssetJSON, "width" | "height"> | null | undefined,
  aspect: string | null | undefined,
  kind: VsKind,
): number {
  if (asset?.width && asset?.height) return asset.width / asset.height;
  return parseAspect(aspect) ?? (kind === "image" ? 1 : 16 / 9);
}

/** Имя файла для «Скачать»: esai-video-1a2b3c4d.mp4. */
export function mediaFilename(asset: Pick<AssetJSON, "uid" | "url" | "kind">): string {
  const path = (asset.url || "").split(/[?#]/)[0];
  const m = /\.([a-z0-9]{2,5})$/i.exec(path);
  const ext = m ? m[1].toLowerCase() : asset.kind === "video" ? "mp4" : "jpg";
  const what = asset.kind === "video" ? "video" : "image";
  return `esai-${what}-${(asset.uid || "file").slice(0, 8)}.${ext}`;
}

/* ------------------------------------------------------------------ */
/* Прокрутка                                                           */
/* ------------------------------------------------------------------ */

export function isNearBottom(
  m: { scrollTop: number; clientHeight: number; scrollHeight: number },
  threshold = NEAR_BOTTOM_PX,
): boolean {
  return m.scrollHeight - (m.scrollTop + m.clientHeight) <= threshold;
}

/**
 * Колонка ленты стала ниже: панель запроса выросла (развернули поле, пришли
 * подсказки) или открылась клавиатура. Докручивать ли ленту к низу — да, если
 * до этого она стояла на самом низу: иначе последний ролик ушёл бы под панель.
 * Именно на самом низу (PINNED_BOTTOM_PX), а не «почти внизу»: кто отлистал
 * хоть немного вверх, смотрит на своё место — докрутка сдвинула бы его разом
 * на весь этот отступ, а после сворачивания панели он остался бы внизу, а не
 * там, где был. prevClientHeight — высота колонки до изменения. Ленту, которую
 * не прокручивали (всё помещалось или человек наверху), не трогаем; когда
 * колонка растёт, браузер держит низ сам.
 */
export function keepsBottom(
  m: { scrollTop: number; clientHeight: number; scrollHeight: number },
  prevClientHeight: number,
): boolean {
  if (!(prevClientHeight > m.clientHeight) || m.scrollTop <= 0) return false;
  return isNearBottom({ scrollTop: m.scrollTop, clientHeight: prevClientHeight, scrollHeight: m.scrollHeight }, PINNED_BOTTOM_PX);
}

/** Зазор над карточкой готового результата, когда она встаёт своим верхом. */
export const RESULT_TOP_GAP_PX = 12;

/**
 * Куда прокрутить ленту, когда результат готов. Карточка, которая не помещается
 * в колонку целиком, встаёт своим верхом: там ролик, ради него человек и ждал, —
 * при прокрутке «к низу» от высокого ролика оставались бы нижняя половина и
 * кнопки (жалоба клиента: «готовый результат плохо видно»). Помещается — к
 * самому низу, как раньше. cardTop — верх карточки от начала прокручиваемого
 * содержимого.
 */
export function resultScrollTop(
  cardTop: number,
  cardHeight: number,
  m: { clientHeight: number; scrollHeight: number },
): number {
  const bottom = Math.max(0, m.scrollHeight - m.clientHeight);
  if (cardHeight + RESULT_TOP_GAP_PX <= m.clientHeight) return bottom;
  return Math.max(0, Math.min(bottom, Math.round(cardTop - RESULT_TOP_GAP_PX)));
}

/**
 * Событие окна: карточка или пример заполнили композер («Изменить», «Другая
 * модель», «Последний кадр → первый», «В референсы», пример). detail:
 * {reason: ComposerFillReason}. Композер по нему ставит фокус в редактор.
 */
export const COMPOSER_FILLED_EVENT = "vstudio:composer-filled";

/**
 * Событие окна: опрос увидел, что дубли закрылись (готово, не получилось,
 * потерян). detail: Array<{uid, shot}>. Контейнер по нему перечитывает строки
 * «Истории» этих проектов: «Идёт генерация» и превью считает сервер.
 */
export const TAKES_SETTLED_EVENT = "vstudio:takes-settled";

/**
 * Пропорция примера, если выбранная модель её умеет. Вид примера другой —
 * модель выберет редьюсер, поэтому берём пропорцию, только если её умеют все
 * модели этого вида. null — не трогаем параметры: иначе вместо цены пришёл
 * бы invalid_param.
 */
export function exampleAspect(
  aspect: string | null | undefined,
  models: { video: ModelJSON[]; image: ModelJSON[] } | null | undefined,
  kind: VsKind,
  currentModel: string | null | undefined,
): string | null {
  if (!aspect || !models) return null;
  const list = kind === "image" ? models.image : models.video;
  const fits = (m: ModelJSON) => (m.caps?.aspect_ratios || []).includes(aspect);
  const current = currentModel ? list.find((m) => m.id === currentModel) : undefined;
  if (current) return fits(current) ? aspect : null;
  return list.length > 0 && list.every(fits) ? aspect : null;
}

/** DOM-id карточки: ?take=<uid> и клик по тосту прокручивают к ней. */
export function shotDomId(shotUid: Uid): string {
  return `vs-shot-${shotUid}`;
}

/** Кадр, которому принадлежит дубль: из стора дублей или из takes загруженных кадров. */
export function shotOfTake(
  takeUid: Uid,
  takes: Map<Uid, TakeLite>,
  shots: Map<Uid, ShotJSON>,
): Uid | null {
  const known = takes.get(takeUid);
  if (known) return known.shot;
  for (const s of shots.values()) if ((s.takes || []).some((t) => t.uid === takeUid)) return s.uid;
  return null;
}
