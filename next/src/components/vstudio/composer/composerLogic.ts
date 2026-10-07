/**
 * Видеостудия, композер: чистая логика без React (§9.6).
 *
 * Здесь решается, что написать на кнопке «Создать» (цена, «Пополнить»,
 * «Войти и создать», «Ждём @Image 3…», «Сейчас снимается 2…»), как
 * исправление из fix превращается в действия стора, что показывает счётчик
 * длины, когда цену пересчитать сразу, а когда — после паузы в наборе.
 * Всё это проверяют node-тесты (composerLogic.test.mjs) без браузера.
 */
import { quoteKey } from "@/lib/vstudio/api";
import { issueFixes } from "@/lib/vstudio/errors";
import { countWords, cpLength } from "@/lib/vstudio/promptDoc";
import { OPEN_TAKE_STATUSES } from "@/lib/vstudio/types";
import type {
  AssetJSON,
  CompilerIssue,
  ComposerState,
  FrameSlot,
  InputSlot,
  IssueFix,
  MeterLevel,
  ModelJSON,
  PromptMeterJSON,
  QuoteBody,
  QuoteJSON,
  RefLabels,
  TakeLite,
  TrayItem,
  TrayStatus,
  Uid,
  VsAction,
  VsError,
  VsFunnelMeta,
  VsKind,
} from "@/lib/vstudio/types";

/* ------------------------------------------------------------------ */
/* Константы                                                           */
/* ------------------------------------------------------------------ */

/** Пауза после набора текста перед пересчётом цены (§9.4). */
export const TEXT_QUOTE_DELAY_MS = 700;
/** Лимит открытых генераций на человека (решение 5): 2 видео + 4 картинки. */
export const OPEN_LIMIT: Record<VsKind, number> = { video: 2, image: 4 };
/** После ответа запуска кнопка ещё столько «Запущено ✓»: второй клик не создаст второй дубль. */
export const RUN_COOLDOWN_MS = 1500;
/** Сколько подсказок видно сразу; остальные — «Ещё N». */
export const HINTS_VISIBLE = 3;
/** Порог «похоже на сценарий» (§4.4 п. 6). */
export const SCRIPT_MIN_CHARS = 1500;

const FRAME_KEYS: readonly FrameSlot[] = ["first_frame", "last_frame"];

/* ------------------------------------------------------------------ */
/* Материалы запроса                                                   */
/* ------------------------------------------------------------------ */

export type ComposerItems = Pick<ComposerState, "tray" | "frames">;

/** Все чипы: лоток, потом кадры. */
export function allItems(c: ComposerItems): TrayItem[] {
  const out = [...c.tray];
  for (const k of FRAME_KEYS) {
    const f = c.frames[k];
    if (f) out.push(f);
  }
  return out;
}

export type InputSummary = {
  /** Включённые референсы с uid (уходят модели как @Image N). */
  refs: number;
  /** Включённые кадры с uid. */
  frames: number;
  /** Сколько чипов ещё грузится (uploading/processing). */
  uploading: number;
  /** Первый включённый чип, который ещё создаётся («Ждём @Image 3…»). */
  pending: TrayItem | null;
  /** Загрузка не удалась: у чипа нет uid, модель его не получит. */
  failedUploads: number;
  /** Всего материалов (лимит 16). */
  total: number;
};

const LOADING: readonly TrayStatus[] = ["uploading", "processing"];

export function summarize(c: ComposerItems): InputSummary {
  const s: InputSummary = { refs: 0, frames: 0, uploading: 0, pending: null, failedUploads: 0, total: 0 };
  const visit = (item: TrayItem, frame: boolean) => {
    s.total += 1;
    if (LOADING.includes(item.status)) {
      s.uploading += 1;
      return;
    }
    if (!item.assetUid) {
      if (item.status === "failed") s.failedUploads += 1;
      return;
    }
    if (!item.included) return;
    if (item.status === "pending" && !s.pending) s.pending = item;
    if (frame) s.frames += 1;
    else s.refs += 1;
  };
  for (const item of c.tray) visit(item, false);
  for (const k of FRAME_KEYS) {
    const f = c.frames[k];
    if (f) visit(f, true);
  }
  return s;
}

/** Сколько генераций этого вида сейчас идёт (по дубям, которые знает вкладка). */
export function countOpen(takes: Iterable<TakeLite>, kind: VsKind): number {
  let n = 0;
  for (const t of takes) if (t.kind === kind && OPEN_TAKE_STATUSES.includes(t.status)) n += 1;
  return n;
}

/** Номер, который получит новая картинка из «Создать картинку» (в конец лотка). */
export function nextRefNumber(tray: readonly TrayItem[]): number {
  const seen = new Set<Uid>();
  let n = 0;
  for (const item of tray) {
    if (!item.included || !item.assetUid || seen.has(item.assetUid)) continue;
    seen.add(item.assetUid);
    n += 1;
  }
  return n + 1;
}

/** Чип лотка из ассета (библиотека, «Создать картинку»). lid стабилен: источник + uid. */
export function trayItemFromAsset(asset: AssetJSON, slot: InputSlot, prefix = "lib"): TrayItem {
  const status: TrayStatus = asset.status === "ready" ? "ready" : asset.status === "failed" ? "failed" : "pending";
  return {
    lid: `${prefix}:${slot}:${asset.uid}`,
    assetUid: asset.uid,
    slot,
    role: "",
    included: true,
    status,
    progress: 100,
    preview: asset.thumb_url || asset.url,
    asset,
    ...(status === "failed" ? { errorCode: asset.error_code || "asset_failed" } : {}),
  };
}

/** Есть ли этот ассет в запросе (в любом слоте или только в данном). */
export function hasAssetIn(c: ComposerItems, uid: Uid, slot?: InputSlot): boolean {
  if (!slot || slot === "reference") {
    if (c.tray.some((i) => i.assetUid === uid)) return true;
    if (slot === "reference") return false;
  }
  for (const k of FRAME_KEYS) {
    if ((!slot || slot === k) && c.frames[k]?.assetUid === uid) return true;
  }
  return false;
}

/** lid всех чипов с этими ассетами (в лотке и кадрах); slot — только в нём. */
export function lidsForAssets(c: ComposerItems, uids: readonly Uid[], slot?: "reference" | "frames"): string[] {
  const want = new Set(uids);
  const out: string[] = [];
  if (slot !== "frames") for (const i of c.tray) if (i.assetUid && want.has(i.assetUid)) out.push(i.lid);
  if (slot !== "reference") {
    for (const k of FRAME_KEYS) {
      const f = c.frames[k];
      if (f?.assetUid && want.has(f.assetUid)) out.push(f.lid);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Исправления из fix (§4.7)                                           */
/* ------------------------------------------------------------------ */

export type FixPlan =
  | { kind: "actions"; actions: VsAction[] }
  | { kind: "condense" }
  | { kind: "topup" }
  | { kind: "pick_model"; model: string | null }
  | { kind: "none" };

/**
 * Что сделать по кнопке исправления. Выключенное не удаляется (§0 п. 9):
 * «Оставить кадры» гасит референсы, «Оставить референсы» — кадры, серые
 * чипы остаются и не оплачиваются.
 */
export function planFix(fix: IssueFix | null | undefined, c: ComposerItems): FixPlan {
  if (!fix) return { kind: "none" };
  switch (fix.action) {
    case "condense":
      return { kind: "condense" };
    case "topup":
      return { kind: "topup" };
    case "pick_model":
      return { kind: "pick_model", model: typeof fix.model === "string" && fix.model ? fix.model : null };
    case "exclude_inputs": {
      const lids = lidsForAssets(c, Array.isArray(fix.assets) ? fix.assets : []);
      return lids.length ? { kind: "actions", actions: [{ type: "tray/include", lids, included: false }] } : { kind: "none" };
    }
    case "move_to_first_frame": {
      const item = c.tray.find((i) => i.assetUid === fix.asset);
      if (!item) return { kind: "none" };
      return { kind: "actions", actions: [{ type: "tray/slot", lid: item.lid, slot: "first_frame" }] };
    }
    case "use_frames_only": {
      const lids =
        Array.isArray(fix.assets) && fix.assets.length
          ? lidsForAssets(c, fix.assets, "reference")
          : c.tray.filter((i) => i.included).map((i) => i.lid);
      return lids.length ? { kind: "actions", actions: [{ type: "tray/include", lids, included: false }] } : { kind: "none" };
    }
    case "use_refs_only": {
      const lids =
        Array.isArray(fix.assets) && fix.assets.length
          ? lidsForAssets(c, fix.assets, "frames")
          : FRAME_KEYS.map((k) => c.frames[k]).filter((f): f is TrayItem => Boolean(f && f.included)).map((f) => f.lid);
      return lids.length ? { kind: "actions", actions: [{ type: "tray/include", lids, included: false }] } : { kind: "none" };
    }
    case "set_param": {
      if (!fix.field) return { kind: "none" };
      return { kind: "actions", actions: [{ type: "composer/params", params: { [fix.field]: fix.value } }] };
    }
    default:
      return { kind: "none" };
  }
}

/** i18n-ключ подписи кнопки исправления. */
export function fixLabelKey(fix: IssueFix):
  | "fix.condense"
  | "fix.exclude"
  | "fix.moveToFirstFrame"
  | "fix.useFrames"
  | "fix.useRefs"
  | "fix.apply"
  | "fix.applyParam"
  | "fix.pickModel"
  | "fix.topup" {
  switch (fix.action) {
    case "condense":
      return "fix.condense";
    case "exclude_inputs":
      return "fix.exclude";
    case "move_to_first_frame":
      return "fix.moveToFirstFrame";
    case "use_frames_only":
      return "fix.useFrames";
    case "use_refs_only":
      return "fix.useRefs";
    case "set_param":
      return fix.value == null || fix.value === "" ? "fix.applyParam" : "fix.apply";
    case "pick_model":
      return "fix.pickModel";
    default:
      return "fix.topup";
  }
}

/* ------------------------------------------------------------------ */
/* Подсказки: что куда                                                 */
/* ------------------------------------------------------------------ */

const CONFLICT_CODES = new Set(["frames_refs_conflict", "last_frame_with_refs"]);
/** Уже видны на самих чипах («не учитывается и не оплачивается») — в списке не повторяем. */
const HIDDEN_WARNINGS = new Set(["input_excluded"]);

export type HintItem = { issue: CompilerIssue; tone: "error" | "warning" };

export type HintGroups = {
  /** Кадры + референсы: ConflictBanner с двумя кнопками. */
  conflict: CompilerIssue | null;
  /** «Похоже на сценарий»: своя плашка. */
  script: CompilerIssue | null;
  /** prompt_long / prompt_too_long: счётчик длины. */
  length: CompilerIssue | null;
  /** Всё остальное: сначала ошибки, потом предупреждения. */
  list: HintItem[];
};

export function groupHints(
  quote: Pick<QuoteJSON, "errors" | "warnings"> | null | undefined,
  opts: { emptyText?: boolean } = {},
): HintGroups {
  const out: HintGroups = { conflict: null, script: null, length: null, list: [] };
  if (!quote) return out;
  const seen = new Set<string>();
  const key = (i: CompilerIssue) => `${i.code}|${JSON.stringify(i.params || {})}`;
  for (const issue of quote.errors || []) {
    if (seen.has(key(issue))) continue;
    seen.add(key(issue));
    // Человек ещё ничего не написал — красное «Опишите, что…» над пустым полем только пугает.
    if (issue.code === "prompt_empty" && opts.emptyText) continue;
    if (CONFLICT_CODES.has(String(issue.code)) && !out.conflict) {
      out.conflict = issue;
      continue;
    }
    if (issue.code === "prompt_too_long" && !out.length) out.length = issue;
    out.list.push({ issue, tone: "error" });
  }
  for (const issue of quote.warnings || []) {
    const code = String(issue.code);
    if (HIDDEN_WARNINGS.has(code) || seen.has(key(issue))) continue;
    seen.add(key(issue));
    if (code === "looks_like_script") {
      out.script = out.script || issue;
      continue;
    }
    if (code === "prompt_long") {
      out.length = out.length || issue;
      continue;
    }
    out.list.push({ issue, tone: "warning" });
  }
  return out;
}

/** Исправления для ConflictBanner: с сервера, а если их нет — те же две кнопки своими силами. */
export function conflictFixes(issue: CompilerIssue): IssueFix[] {
  const fixes = issueFixes(issue);
  if (fixes.length) return fixes;
  if (issue.code === "frames_refs_conflict") return [{ action: "use_frames_only" }, { action: "use_refs_only" }];
  return [{ action: "use_frames_only" }];
}

/** uid материалов, на которые показывают ошибки (подсветить чипы красным). */
export function flaggedAssets(errors: readonly CompilerIssue[] | null | undefined): Set<Uid> {
  const out = new Set<Uid>();
  for (const e of errors || []) {
    const p = e.params || {};
    if (typeof p.asset === "string") out.add(p.asset);
    if (Array.isArray(p.assets)) for (const a of p.assets) if (typeof a === "string") out.add(a);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Счётчик длины (§4.8)                                                */
/* ------------------------------------------------------------------ */

export type MeterView = {
  chars: number;
  words: number;
  soft: number | null;
  hard: number;
  level: MeterLevel;
  /** 0…1 — заполненность полоски (мягкий лимит по словам или жёсткий по символам). */
  ratio: number;
  /** true — цифры подтвердил сервер (свежий quote). */
  exact: boolean;
};

/**
 * Счётчик: мгновенно по тексту на клиенте, а свежий quote подтверждает
 * (сервер считает сериализованный текст — с заголовком ролей и тегами модели).
 */
export function meterView(
  text: string,
  model: Pick<ModelJSON, "caps"> | null | undefined,
  serverMeter?: PromptMeterJSON | null,
): MeterView {
  const fill = (chars: number, words: number, soft: number | null, hard: number) =>
    Math.max(hard > 0 ? chars / hard : 0, soft ? Math.min(words / soft, 1) : 0);
  if (serverMeter) {
    return {
      chars: serverMeter.chars,
      words: serverMeter.words,
      soft: serverMeter.soft_words,
      hard: serverMeter.hard_chars,
      level: serverMeter.level,
      ratio: fill(serverMeter.chars, serverMeter.words, serverMeter.soft_words, serverMeter.hard_chars),
      exact: true,
    };
  }
  const caps = model?.caps?.prompt;
  const chars = cpLength(text);
  const words = countWords(text);
  const soft = caps?.soft_words ?? null;
  const hard = caps?.hard_chars ?? 20000;
  let level: MeterLevel = "ok";
  if (chars > hard) level = "hard";
  else if (soft && words > soft) level = "soft";
  return { chars, words, soft, hard, level, ratio: fill(chars, words, soft, hard), exact: false };
}

// Зеркало compiler.script_signs. Без lookbehind: Safari до 16.4 падает на
// (?<!…) ещё при разборе файла — граница слова задаётся захватом соседа.
const SCRIPT_SIGNS: Array<{ re: RegExp; max: number }> = [
  { re: /^\s*(?:сцена|scene|кадр|shot)\s*\d+/gimu, max: 2 },
  { re: /(?:^|\D)\d{1,2}:\d{2}(?!\d)/gu, max: 2 },
  { re: /^\s*\d{1,2}[.)]\s+\S/gmu, max: 2 },
  { re: /(?:^|[^\p{L}\p{N}_])(?:затем|потом|после этого|then)(?![\p{L}\p{N}_])/giu, max: 1 },
];

/** Сколько признаков сценария: «Сцена N», таймкоды, нумерованный список (до двух каждого), «затем/потом» (один). */
export function scriptSigns(text: string): number {
  let n = 0;
  for (const { re, max } of SCRIPT_SIGNS) n += Math.min((text.match(re) || []).length, max);
  return n;
}

/** «Похоже на сценарий»: длиннее 1500 символов и не меньше двух признаков (то же правило, что у компилятора). */
export function looksLikeScript(text: string): boolean {
  return cpLength(text) > SCRIPT_MIN_CHARS && scriptSigns(text) >= 2;
}

/* ------------------------------------------------------------------ */
/* Цена: когда пересчитывать                                          */
/* ------------------------------------------------------------------ */

/** Тело для запасной textarea: prompt_text вместо prompt_doc (теги разберёт сервер). */
export function withPromptText(body: QuoteBody | null, promptText: string | null | undefined): QuoteBody | null {
  if (!body || promptText == null) return body;
  const { prompt_doc: _doc, ...rest } = body;
  void _doc;
  return { ...rest, prompt_text: promptText };
}

/** Тело без текста: смена модели, параметров или лотка — пересчёт сразу. */
export function structureKey(body: QuoteBody | null): string {
  if (!body) return "";
  const rest: Record<string, unknown> = { ...body };
  delete rest.prompt_doc;
  delete rest.prompt_text;
  return quoteKey(rest as unknown as QuoteBody);
}

/**
 * Состояние материалов, которого нет в теле: чип «создаётся» стал готовым —
 * тело то же, а ответ компилятора (asset_not_ready) уже устарел.
 */
export function statusSignature(c: ComposerItems): string {
  return allItems(c)
    .filter((i) => i.assetUid)
    .map((i) => `${i.assetUid}:${i.status === "ready" ? "r" : i.status === "pending" ? "p" : i.status === "deleted" ? "d" : i.status === "failed" ? "f" : "u"}`)
    .join(",");
}

export type QuoteTrigger = { key: string; structure: string; extra: string };

/**
 * Через сколько спросить цену: null — ничего не изменилось, 0 — сразу
 * (модель, параметры, лоток, статусы), TEXT_QUOTE_DELAY_MS — изменился только текст.
 */
export function quoteDelay(prev: QuoteTrigger | null, next: QuoteTrigger): number | null {
  if (!next.key) return null;
  if (!prev) return 0;
  if (prev.key === next.key && prev.extra === next.extra) return null;
  if (prev.structure !== next.structure || prev.extra !== next.extra) return 0;
  return TEXT_QUOTE_DELAY_MS;
}

/* ------------------------------------------------------------------ */
/* Кнопка «Создать» (§9.6)                                             */
/* ------------------------------------------------------------------ */

export type RunView =
  | { kind: "sending" }
  | { kind: "started" }
  | { kind: "signin" }
  | { kind: "no_model" }
  | { kind: "uploading"; count: number }
  | { kind: "waiting"; item: TrayItem }
  | { kind: "failed_upload" }
  | { kind: "limit"; n: number; of: VsKind }
  | { kind: "blocked"; issue: CompilerIssue }
  | { kind: "no_price"; error: VsError | null }
  | { kind: "locked"; credits: number }
  | { kind: "topup"; credits: number; missing: number }
  | { kind: "quoting"; credits: number | null }
  | { kind: "run"; credits: number };

export type RunViewInput = {
  authed: boolean | null;
  model: Pick<ModelJSON, "locked"> | null;
  kind: VsKind;
  sending: boolean;
  cooldown: boolean;
  summary: InputSummary;
  /** Свежий quote: его key совпал с текущим телом. */
  fresh: QuoteJSON | null;
  quoteStatus: "idle" | "loading" | "ready" | "error";
  quoteError: VsError | null;
  /** Последняя известная цена при той же структуре (пока меняется только текст). */
  lastCredits: number | null;
  openCount: number;
  /** 409 too_many_open — держим, пока не закроется хоть один дубль. */
  limitHit: { kind: VsKind; limit: number | null } | null;
};

/** Что показать на кнопке. Порядок — от того, что мешает сильнее. */
export function runView(i: RunViewInput): RunView {
  if (i.sending) return { kind: "sending" };
  if (i.cooldown) return { kind: "started" };
  if (i.authed === false) return { kind: "signin" };
  if (!i.model) return { kind: "no_model" };
  if (i.summary.uploading > 0) return { kind: "uploading", count: i.summary.uploading };
  if (i.summary.pending) return { kind: "waiting", item: i.summary.pending };
  if (i.summary.failedUploads > 0) return { kind: "failed_upload" };
  const limit = OPEN_LIMIT[i.kind];
  const hit = i.limitHit && i.limitHit.kind === i.kind ? i.limitHit : null;
  if (i.openCount >= limit || hit) {
    return { kind: "limit", n: hit ? Math.max(i.openCount, hit.limit ?? limit) : i.openCount, of: i.kind };
  }
  const q = i.fresh;
  if (q) {
    if (q.errors && q.errors.length) return { kind: "blocked", issue: q.errors[0] };
    if (q.credits == null) return { kind: "no_price", error: null };
    if (i.model.locked) return { kind: "locked", credits: q.credits };
    const available = q.balance?.available;
    if (typeof available === "number" && available < q.credits) {
      return { kind: "topup", credits: q.credits, missing: Math.max(1, Math.ceil(q.credits - available)) };
    }
    return { kind: "run", credits: q.credits };
  }
  if (i.quoteStatus === "error") return { kind: "no_price", error: i.quoteError };
  return { kind: "quoting", credits: i.lastCredits };
}

/**
 * Сколько кредитов не хватает по этой цене; 0 — хватает или баланса в ответе нет (гость).
 * Остаток приходит вместе с ценой, а тело запроса от оплаты не меняется: после пополнения
 * его обновит только новый quote — по этому числу решаем, спрашивать ли цену заново.
 */
export function quoteMissing(q: Pick<QuoteJSON, "credits" | "balance"> | null | undefined): number {
  const available = q?.balance?.available;
  if (!q || q.credits == null || typeof available !== "number" || available >= q.credits) return 0;
  return Math.max(1, Math.ceil(q.credits - available));
}

/** Можно ли нажать (сама кнопка; blocked нажимается, чтобы показать причину). */
export function runClickable(v: RunView): boolean {
  return (
    v.kind === "run" ||
    v.kind === "topup" ||
    v.kind === "signin" ||
    v.kind === "locked" ||
    v.kind === "quoting" ||
    v.kind === "no_price" ||
    v.kind === "blocked" ||
    v.kind === "failed_upload"
  );
}

/** meta для vstudio_run_click (§11). */
export function runClickMeta(
  model: string,
  kind: VsKind,
  credits: number | null,
  summary: InputSummary,
  text: string,
): VsFunnelMeta["vstudio_run_click"] {
  return { model, kind, credits, refs: summary.refs, frames: summary.frames, words: countWords(text) };
}

/* ------------------------------------------------------------------ */
/* Мелочи                                                              */
/* ------------------------------------------------------------------ */

/** 1 200 — пробел тысяч как в остальном сайте (ru-RU). */
export function fmtNum(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "";
  return Math.round(n).toLocaleString("ru-RU");
}

/** Номер «@Image N» чипа из меток (null — кадр, выключен или ещё без uid). */
export function chipNumber(labels: RefLabels, item: TrayItem): number | null {
  return item.assetUid ? labels[item.assetUid]?.n ?? null : null;
}

/** Сдвиг чипа в лотке на ±1 (кнопки ‹ › на телефоне). null — дальше некуда. */
export function moveTarget(tray: readonly TrayItem[], lid: string, delta: -1 | 1): number | null {
  const i = tray.findIndex((x) => x.lid === lid);
  if (i < 0) return null;
  const to = i + delta;
  return to < 0 || to >= tray.length ? null : to;
}
