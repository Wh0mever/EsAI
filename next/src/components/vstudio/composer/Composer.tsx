"use client";

/**
 * Видеостудия: композер — прилипшая к низу панель запроса (§9.2, §9.6, §9.7).
 *
 * Сверху вниз: подсказки компилятора с кнопками исправления, плашка
 * конфликта кадров и референсов, «Похоже на сценарий»; дальше стеклянная
 * панель: лоток материалов (@Image N) и слоты кадров; поле промпта
 * (PromptEditor, FE-2); строка-разделитель со счётчиком длины и «Сжать с ИИ»;
 * чипы параметров (SettingsPills), «@» и кнопка «Создать · N кр». На телефоне
 * — полоса материалов, поле и строка «чип параметров · @ · Создать».
 *
 * Первый экран зовёт панель через composerBus: открыть выбор файла, «Создать
 * картинку», показать слоты кадров, поставить фокус в поле.
 *
 * Деньги: цену считает только сервер (quote/, тот же компилятор, что и запуск),
 * запуск уходит с ценой из quote с тем же телом (key), client_request_id живёт
 * от клика до ответа — повторный клик не платит дважды, а после обрыва сети
 * тот же клик повторяется с тем же id.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiAtSign } from "react-icons/fi";
import { buildInputs, condense as condenseApi, newClientRequestId, runShot, trackVs } from "@/lib/vstudio/api";
import { errorText, firstBlockingCode, reactionFor } from "@/lib/vstudio/errors";
import { buildRefLabels, pickerItemsFrom, serverLabels } from "@/lib/vstudio/labels";
import { isEmptyDoc, plainText, renderText } from "@/lib/vstudio/promptDoc";
import { UPLOAD_ACCEPT } from "@/lib/vstudio/upload";
import type { AssetJSON, FrameSlot, InputSlot, IssueFix, PromptEditorHandle, Uid, VsKind } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import PromptEditor, { preloadPromptEditor } from "../editor/PromptEditor";
import { COMPOSER_FILLED_EVENT } from "../feed/feedLogic";
import { useQuote } from "../hooks/useQuote";
import { useUpload } from "../hooks/useUpload";
import { useLibrary } from "../library/AssetLibrarySheet";
import { openModelPicker } from "../settings/ModelPicker";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { SettingsChip } from "../settings/SettingsSheet";
import { selectModel as selectModelChoice } from "../settings/useRunSettingsSync";
import { selectModel } from "../store";
import { VS_ICON_BTN, VS_PANEL, vx } from "../ui/skin";
import AssetTray, { type ChipHandlers } from "./AssetTray";
import { registerComposer, setLibraryTarget } from "./composerBus";
import {
  RUN_COOLDOWN_MS,
  countOpen,
  flaggedAssets,
  groupHints,
  hasAssetIn,
  looksLikeScript,
  meterView,
  moveTarget,
  planFix,
  quoteMissing,
  runClickMeta,
  runView,
  summarize,
  trayItemFromAsset,
} from "./composerLogic";
import { ct } from "./composerText";
import ComposerHints, { ScriptBanner } from "./ComposerHints";
import CondenseDiffDialog, { type CondenseResult } from "./CondenseDiffDialog";
import ConflictBanner from "./ConflictBanner";
import FrameSlots, { showFrameSlots } from "./FrameSlots";
import ImageGenMini from "./ImageGenMini";
import PromptMeter from "./PromptMeter";
import RunButton, { PriceInfoButton, quietReason, runTexts } from "./RunButton";
import SettingsPills from "./SettingsPills";
import { useBalanceRequote } from "./useBalanceRequote";

/** Сколько держим «Сейчас снимается 2…» после 409 too_many_open, если вкладка не видит этих дублей. */
const LIMIT_HOLD_MS = 20_000;
/** Сколько подсвечены слоты кадров, когда к ним привёл первый экран: два круга кольца vs-ready. */
const FRAMES_PULSE_MS = 4800;

type Condense = { status: "idle" } | { status: "loading" } | { status: "ready"; result: CondenseResult };

export default function Composer() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions, authed, breakpoint } = useVStudio();
  const { composer, models, run, ui, library } = state;
  const mobile = breakpoint === "mobile";
  const model = selectModel(state);

  const [promptText, setPromptText] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  const [limitHit, setLimitHit] = useState<{ kind: VsKind; limit: number | null } | null>(null);
  const [condense, setCondense] = useState<Condense>({ status: "idle" });
  const [imageGen, setImageGen] = useState<null | "editor" | "tray">(null);
  const [scriptDismissed, setScriptDismissed] = useState<number | null>(null);
  const [framesPulse, setFramesPulse] = useState(false);

  const editor = useRef<PromptEditorHandle | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const uploadSlot = useRef<InputSlot>("reference");
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  /** Запуск, оборвавшийся без ответа: следующий клик с тем же телом уйдёт с тем же id. */
  const pendingRun = useRef<{ id: string; key: string } | null>(null);
  /** Номер последней подсветки слотов кадров: гасит её только свой таймер, а не таймер прошлого нажатия. */
  const pulseSeq = useRef(0);

  const { addFiles, retry: retryUpload, cancel: cancelUpload, remove: removeItem } = useUpload();
  const quote = useQuote({ promptText, enabled: state.available && state.mode !== "off" });
  // Первая страница «Моих материалов» — для раздела выбора по «@».
  useLibrary(authed === true);

  /* ---------- производные ---------- */

  const labels = useMemo(
    () => buildRefLabels({ tray: composer.tray, frames: composer.frames }, t),
    [composer.tray, composer.frames, t],
  );
  const pickerItems = useMemo(
    () => pickerItemsFrom({ tray: composer.tray, frames: composer.frames, library: library.items }, labels),
    [composer.tray, composer.frames, library.items, labels],
  );
  const summary = useMemo(() => summarize(composer), [composer]);
  const fresh = quote.fresh;
  // Пока текст пересчитывается, показываем прошлые подсказки той же структуры — без мигания.
  const shownQuote = fresh ?? quote.last;
  const emptyText = promptText != null ? promptText.trim() === "" : isEmptyDoc(composer.doc);
  const hints = useMemo(() => groupHints(shownQuote, { emptyText }), [shownQuote, emptyText]);
  const flagged = useMemo(() => flaggedAssets(shownQuote?.errors), [shownQuote]);
  const text = useMemo(
    () => promptText ?? renderText(composer.doc, serverLabels(labels)),
    [promptText, composer.doc, labels],
  );
  const meter = meterView(text, model, fresh?.meter ?? null);
  const openCount = countOpen(state.takes.values(), composer.kind);
  const frameSlots = composer.kind === "video" ? model?.caps.frames ?? [] : [];
  const imageModels = models?.image.length ?? 0;

  // Закрылась одна из генераций — «Сейчас снимается 2…» больше не держим.
  const [prevOpen, setPrevOpen] = useState(openCount);
  if (openCount !== prevOpen) {
    setPrevOpen(openCount);
    if (openCount < prevOpen && limitHit) setLimitHit(null);
  }

  const view = runView({
    authed,
    model,
    kind: composer.kind,
    sending: checking || run.status === "sending",
    cooldown,
    summary,
    fresh,
    quoteStatus: quote.error ? "error" : fresh ? "ready" : quote.loading ? "loading" : "idle",
    quoteError: quote.error,
    lastCredits: quote.lastCredits,
    openCount,
    limitHit,
  });

  const scriptBucket = Math.round(meter.chars / 1000);
  const isScript = Boolean(hints.script) || (!fresh && looksLikeScript(plainText(composer.doc)));
  const showScript = isScript && scriptDismissed !== scriptBucket;

  /* ---------- свежие значения для обработчиков ---------- */

  const live = useRef({ state, quote, view, model, labels, text, summary });
  useLayoutEffect(() => {
    live.current = { state, quote, view, model, labels, text, summary };
  });

  const later = useCallback((fn: () => void, ms: number) => {
    const id = setTimeout(() => {
      timers.current.delete(id);
      fn();
    }, ms);
    timers.current.add(id);
  }, []);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const id of pending) clearTimeout(id);
      pending.clear();
    };
  }, []);

  /* ---------- редактор ---------- */

  useEffect(() => {
    preloadPromptEditor();
  }, []);

  const focusPrompt = useCallback(() => {
    editor.current?.focus();
    if (mobile) boxRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [mobile]);

  // Карточка ленты заполнила композер («Изменить», «Другая модель», пример) — фокус в поле.
  useEffect(() => {
    window.addEventListener(COMPOSER_FILLED_EVENT, focusPrompt);
    return () => window.removeEventListener(COMPOSER_FILLED_EVENT, focusPrompt);
  }, [focusPrompt]);

  // «Первый и последний кадр» с первого экрана: слоты в поле зрения, подсвечены, фокус на первом.
  const focusFrames = useCallback(() => {
    // Карточка могла только что сменить модель: слоты появятся после рендера — ждём его.
    later(() => {
      const slots = boxRef.current?.querySelector<HTMLElement>("[data-vs-frames]");
      // Модель без кадров или вид «Картинка» — слотов нет, остаётся поле запроса.
      if (!slots) {
        focusPrompt();
        return;
      }
      // На телефоне слоты стоят в конце полосы материалов — докручиваем полосу до них.
      slots.scrollIntoView({ block: "nearest", inline: "nearest" });
      slots.querySelector<HTMLElement>("button, [role='button']")?.focus({ preventScroll: true });
      const seq = ++pulseSeq.current;
      setFramesPulse(true);
      later(() => {
        if (pulseSeq.current === seq) setFramesPulse(false);
      }, FRAMES_PULSE_MS);
    }, 0);
  }, [later, focusPrompt]);

  const addAsset = useCallback(
    (asset: AssetJSON, slot: InputSlot = "reference", prefix = "lib") => {
      const c = live.current.state.composer;
      if (hasAssetIn(c, asset.uid, slot)) return false;
      if (slot !== "reference" && c.kind !== "video") dispatch({ type: "composer/kind", kind: "video" });
      dispatch({ type: "tray/add", item: trayItemFromAsset(asset, slot, prefix) });
      return true;
    },
    [dispatch],
  );

  const onPickLibrary = useCallback(
    (uid: Uid) => {
      const asset = live.current.state.library.items.find((a) => a.uid === uid);
      if (asset) addAsset(asset, "reference");
    },
    [addAsset],
  );

  const onEditorUpload = useCallback((files: File[]) => addFiles(files, { slot: "reference" }), [addFiles]);

  /* ---------- загрузка и библиотека ---------- */

  const pickFiles = useCallback(
    (slot: InputSlot) => {
      if (!actions.requireAuth()) return;
      uploadSlot.current = slot;
      const input = fileInput.current;
      if (!input) return;
      input.multiple = slot === "reference";
      input.click();
    },
    [actions],
  );

  const openLibrary = (slot: FrameSlot | null) => {
    setLibraryTarget(slot);
    actions.openLibrary();
  };

  /* ---------- чипы ---------- */

  const handlers = useMemo<ChipHandlers>(
    () => ({
      retry: retryUpload,
      cancel: cancelUpload,
      remove: removeItem,
      include: (lid, included) => dispatch({ type: "tray/include", lids: [lid], included }),
      role: (lid, role) => dispatch({ type: "tray/role", lid, role }),
      slot: (lid, slot) => {
        if (slot !== "reference" && live.current.state.composer.kind !== "video") dispatch({ type: "composer/kind", kind: "video" });
        dispatch({ type: "tray/slot", lid, slot });
      },
      move: (lid, delta) => {
        const to = moveTarget(live.current.state.composer.tray, lid, delta);
        if (to !== null) dispatch({ type: "tray/move", lid, to });
      },
      moveTo: (lid, to) => dispatch({ type: "tray/move", lid, to }),
      insert: (lid) => {
        const c = live.current.state.composer;
        const item = [...c.tray, c.frames.first_frame, c.frames.last_frame].find((i) => i?.lid === lid);
        if (!item?.assetUid) return;
        editor.current?.insertRef(item.assetUid);
        trackVs("vstudio_mention", { via: "button" });
      },
    }),
    [retryUpload, cancelUpload, removeItem, dispatch],
  );

  /* ---------- «Сжать с ИИ» ---------- */

  const runCondense = useCallback(async () => {
    const s = live.current.state;
    const m = live.current.model;
    if (!m || condense.status === "loading") return;
    if (!actions.requireAuth()) return;
    const doc = s.composer.doc;
    setCondense({ status: "loading" });
    const res = await condenseApi({ model: m.id, prompt_doc: doc, inputs: buildInputs(s.composer.tray, s.composer.frames) });
    if (!res.ok) {
      setCondense({ status: "idle" });
      const r = actions.handleError(res.error, { silent: true });
      if (r.kind !== "auth" && r.kind !== "paywall" && r.kind !== "disabled" && r.kind !== "ignore") {
        actions.toast(errorText(t, res.error), "error");
      }
      return;
    }
    setCondense({
      status: "ready",
      result: { before: doc, after: res.data.prompt_doc, statsBefore: res.data.before, statsAfter: res.data.after },
    });
  }, [actions, condense.status, t]);

  const finishCondense = (accepted: boolean) => {
    if (condense.status === "ready" && accepted) dispatch({ type: "composer/doc", doc: condense.result.after });
    trackVs("vstudio_condense", { accepted, ...(live.current.model ? { model: live.current.model.id } : {}) });
    setCondense({ status: "idle" });
    requestAnimationFrame(() => editor.current?.focus());
  };

  /* ---------- исправления ---------- */

  const onFix = useCallback(
    (fix: IssueFix) => {
      const c = live.current.state.composer;
      const plan = planFix(fix, c);
      switch (plan.kind) {
        case "actions":
          for (const a of plan.actions) dispatch(a);
          break;
        case "condense":
          void runCondense();
          break;
        case "topup":
          trackVs("vstudio_paywall");
          actions.openTopUp();
          break;
        case "pick_model": {
          const s = live.current.state;
          if (plan.model) {
            selectModelChoice(dispatch, s.models, { kind: c.kind, model: c.model, params: c.params }, plan.model);
          } else {
            // С 768 px список моделей открывается в окошке у чипа модели (SettingsPills),
            // на телефоне — в шторке параметров.
            if (mobile) dispatch({ type: "ui/panel", panel: "settings", open: true });
            openModelPicker();
          }
          break;
        }
        default:
          break;
      }
    },
    [dispatch, actions, runCondense, mobile],
  );

  /* ---------- запуск ---------- */

  const startRun = useCallback(async () => {
    const { quote: q0, model: m, summary: sum, text: txt } = live.current;
    const v = live.current.view;
    if (!m) return;
    if (!actions.requireAuth()) return;
    const shown = v.kind === "run" || v.kind === "quoting" ? v.credits : null;
    // Тело и его ключ — на момент клика: запуск уйдёт ровно с тем, что оценено.
    const body = q0.body;
    const key = q0.key;
    if (!body) return;
    setChecking(true);
    let res;
    try {
      res = await q0.ensureFresh();
    } finally {
      setChecking(false);
    }
    // Пока ждали цену, человек поменял запрос — на кнопке уже новая цена.
    if (!res || live.current.quote.key !== key) return;
    if (!res.ok) {
      actions.handleError(res.error);
      return;
    }
    const q = res.data;
    if (q.errors.length) {
      trackVs("vstudio_blocked", { code: firstBlockingCode(q.errors) ?? "blocked" });
      return;
    }
    if (q.credits == null) return;
    // Цену человек ещё не видел (на кнопке был скелетон) — сначала показать её.
    if (shown == null) return;
    // Цена поменялась с того, что человек видел: показываем новую и ждём второго клика.
    if (shown !== q.credits) {
      actions.toast(ct(t, "composer.priceChanged", { credits: q.credits }), "info");
      return;
    }
    if (m.locked) {
      openLockedModel(dispatch, { requireAuth: actions.requireAuth });
      return;
    }
    if (q.balance && q.balance.available < q.credits) {
      trackVs("vstudio_paywall");
      actions.openTopUp();
      return;
    }
    const id = pendingRun.current && pendingRun.current.key === key ? pendingRun.current.id : newClientRequestId();
    pendingRun.current = { id, key };
    const c = live.current.state.composer;
    trackVs("vstudio_run_click", runClickMeta(m.id, c.kind, q.credits, sum, txt));
    dispatch({ type: "run/start", clientRequestId: id });
    const out = await runShot({
      ...body,
      quoted_credits: q.credits,
      client_request_id: id,
      origin: "composer",
      // «Изменить» / «Другая модель»: связь с исходным кадром (только для истории).
      ...(c.forkedFrom ? { forked_from: c.forkedFrom } : {}),
    });
    if (out.ok) {
      pendingRun.current = null;
      dispatch({ type: "run/done", response: out.data });
      actions.refreshBalance();
      setCooldown(true);
      later(() => setCooldown(false), RUN_COOLDOWN_MS);
      return;
    }
    const err = out.error;
    dispatch({ type: "run/failed", error: err });
    // Ответа не было — запрос мог дойти. Тот же клик уйдёт с тем же id (сервер вернёт тот же дубль).
    if (err.status !== 0) pendingRun.current = null;
    const r = reactionFor(err);
    switch (r.kind) {
      case "paywall":
        actions.handleError(err);
        trackVs("vstudio_paywall");
        break;
      case "requote":
        live.current.quote.refresh();
        actions.toast(errorText(t, err), "info");
        break;
      case "blocked":
        live.current.quote.refresh();
        trackVs("vstudio_blocked", { code: firstBlockingCode(r.errors) ?? "blocked" });
        break;
      case "limit":
        setLimitHit({ kind: r.of ?? c.kind, limit: r.limit });
        later(() => setLimitHit(null), LIMIT_HOLD_MS);
        break;
      case "not_found":
        actions.toast(errorText(t, err), "error");
        break;
      default:
        actions.handleError(err);
    }
  }, [actions, dispatch, later, t]);

  const onRun = useCallback(() => {
    const v = live.current.view;
    switch (v.kind) {
      case "signin":
        actions.requireAuth();
        return;
      case "locked":
        openLockedModel(dispatch, { requireAuth: actions.requireAuth });
        return;
      case "topup":
        trackVs("vstudio_paywall");
        actions.openTopUp();
        return;
      case "blocked":
        trackVs("vstudio_blocked", { code: String(v.issue.code) });
        boxRef.current?.parentElement?.querySelector("[data-vs-hints]")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        return;
      case "failed_upload":
        trackVs("vstudio_blocked", { code: "upload_failed" });
        return;
      case "no_price":
        live.current.quote.refresh();
        return;
      case "run":
      case "quoting":
        void startRun();
        return;
      default:
        return;
    }
  }, [actions, dispatch, startRun]);

  // Баланс пополнили, а цена на кнопке несёт старый остаток: она так и звала бы «Пополнить» и снова
  // открывала окно оплаты. Спрашиваем заново — но только если по этой цене не хватало: тот же сигнал
  // приходит после каждого запуска, и лишний перезапрос оборвал бы цену, которую ждёт «Создать».
  useBalanceRequote(() => {
    const q = live.current.quote;
    if (quoteMissing(q.fresh) > 0) q.refresh();
  });

  /* ---------- «Создать картинку» ---------- */

  const openImageGen = useCallback(
    (from: "editor" | "tray") => {
      if (!actions.requireAuth()) return;
      setImageGen(from);
    },
    [actions],
  );

  const onImageCreated = (asset: AssetJSON) => {
    const from = imageGen;
    addAsset(asset, "reference", "gen");
    if (from === "editor") requestAnimationFrame(() => editor.current?.insertRef(asset.uid));
  };

  /* ---------- ручки для остальной студии ---------- */

  // Зона перетаскивания, «Мои материалы» и карточки первого экрана живут вне композера — даём им свои ручки.
  useEffect(
    () =>
      registerComposer({
        upload: (files, opts) => addFiles(files, { slot: opts?.slot ?? "reference" }),
        pick: (asset, slot) => {
          if (!addAsset(asset, slot ?? "reference")) actions.toast(ct(t, "composer.alreadyInRequest"), "info");
        },
        openUpload: (slot) => pickFiles(slot ?? "reference"),
        openImageGen: () => openImageGen("tray"),
        focusFrames,
        focusPrompt,
      }),
    [addFiles, addAsset, actions, t, pickFiles, openImageGen, focusFrames, focusPrompt],
  );

  /* ---------- раскладка ---------- */

  const framesVisible = showFrameSlots(composer.kind, model, composer.frames);
  const frames = framesVisible ? (
    <FrameSlots
      frames={composer.frames}
      model={model}
      labels={labels}
      flagged={flagged}
      handlers={handlers}
      onUpload={(slot) => pickFiles(slot)}
      onLibrary={(slot) => {
        if (!actions.requireAuth()) return;
        openLibrary(slot);
      }}
      compact={mobile}
      pulse={framesPulse}
    />
  ) : null;

  const condensing = condense.status === "loading";
  // Почему запуск закрыт — строкой в самой панели, а не под кнопкой: панель не меняет высоту, чипы не прыгают.
  const reason = runTexts(t, view, composer.kind, labels, mobile).reason;
  // Телефон, поле пустое: «опишите, что в кадре» уже говорит подсказка в самом поле, а строка под
  // кнопкой только добавляла бы панели высоту на первом экране. Экранному диктору причина остаётся.
  const reasonUnseen = mobile && emptyText && view.kind === "blocked" && view.issue.code === "prompt_empty";
  const canCondense = meter.level !== "ok" && Boolean(model) && authed !== false;
  const priceInfo = view.kind === "run" || view.kind === "topup" || view.kind === "locked";

  const tray = (
    <AssetTray
      items={composer.tray}
      labels={labels}
      flagged={flagged}
      frameSlots={frameSlots}
      handlers={handlers}
      mobile={mobile}
      onAdd={() => pickFiles("reference")}
      onGenerate={() => openImageGen("tray")}
      onLibrary={() => {
        if (!actions.requireAuth()) return;
        openLibrary(null);
      }}
      trailing={mobile ? frames : null}
      canGenerate={imageModels > 0}
    />
  );
  const meterLine = (
    <PromptMeter
      meter={meter}
      modelName={model?.name || ""}
      onCondense={canCondense ? () => void runCondense() : null}
      condensing={condensing}
      compact={!mobile}
    />
  );
  const mentionButton = (
    <button
      type="button"
      onClick={() => editor.current?.openPicker()}
      aria-label={ct(t, "composer.mentionShort")}
      title={ct(t, "composer.mentionShort")}
      className={VS_ICON_BTN}
    >
      <FiAtSign aria-hidden />
    </button>
  );

  return (
    <div className="flex flex-col gap-2" data-vs-composer="">
      {(hints.list.length > 0 || hints.conflict || showScript) && (
        // На телефоне — доля видимой части окна (--vvh), а не vh: с открытой
        // клавиатурой подсказки иначе съедали место кнопки «Создать».
        <div
          className="flex max-h-[34vh] flex-col gap-2 overflow-y-auto overscroll-contain max-md:max-h-[calc(var(--vvh,100dvh)*0.2)]"
          data-vs-hints=""
        >
          {hints.conflict && <ConflictBanner issue={hints.conflict} onFix={onFix} />}
          {showScript && (
            <ScriptBanner
              onDismiss={() => {
                setScriptDismissed(scriptBucket);
                onRun();
              }}
            />
          )}
          <ComposerHints items={hints.list} onFix={onFix} />
        </div>
      )}

      {/* Стеклянная панель: на телефоне плотнее и с меньшим скруглением — полю нужна ширина. */}
      <div
        ref={boxRef}
        className={vx(
          "flex flex-col gap-2 transition-[border-color] duration-200 focus-within:!border-white/25",
          mobile ? "vs-glass rounded-[20px] p-2" : `${VS_PANEL} p-3`,
        )}
      >
        {mobile ? (
          tray
        ) : (
          // Слоты кадров — в той же строке справа: у моделей с кадрами панель не растёт на строку.
          <div className="flex min-w-0 items-start gap-3">
            <div className="min-w-0 flex-1">{tray}</div>
            {frames}
          </div>
        )}

        {/* Поле без своей подложки: текст лежит прямо на стекле панели. */}
        <PromptEditor
          doc={composer.doc}
          onChange={(doc) => dispatch({ type: "composer/doc", doc })}
          labels={labels}
          pickerItems={pickerItems}
          onPickLibrary={onPickLibrary}
          onUpload={onEditorUpload}
          onGenerate={() => openImageGen("editor")}
          onSubmit={onRun}
          fullscreen={ui.fullscreen}
          onFullscreenChange={(open) => dispatch({ type: "ui/fullscreen", open })}
          disabled={condensing}
          onPromptText={setPromptText}
          handleRef={editor}
        />

        {mobile ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <SettingsChip className="flex-1 justify-start" />
              {mentionButton}
              <RunButton view={view} kind={composer.kind} quote={fresh} labels={labels} onClick={onRun} compact hideReason />
            </div>
            {reason && (
              <p
                className={
                  reasonUnseen
                    ? "sr-only"
                    : `px-1 text-xs leading-snug ${quietReason(view) ? "text-muted" : "text-status-fail"}`
                }
                aria-live="polite"
              >
                {reason}
              </p>
            )}
            {(meter.chars > 0 || priceInfo) && (
              <div className="flex items-start gap-2 px-1">
                <div className="min-w-0 flex-1">{meterLine}</div>
                {priceInfo && <PriceInfoButton quote={fresh} />}
              </div>
            )}
          </div>
        ) : (
          <>
            {/* Разделитель и строка состояния сразу: слева подсказка про клавиши, справа счётчик длины
                и причина, по которой запуск закрыт (она стоит над кнопкой «Создать»). */}
            <div className="flex min-h-4 items-center gap-3">
              {!emptyText && <span className="hidden shrink-0 text-[11px] text-muted-2 xl:inline">{ct(t, "composer.shortcut")}</span>}
              <span className="h-px min-w-6 flex-1 bg-white/[0.08]" aria-hidden />
              {meterLine}
              {reason && (
                <p
                  className={`max-w-[22rem] text-right text-xs leading-snug ${quietReason(view) ? "text-muted" : "text-status-fail"}`}
                  aria-live="polite"
                >
                  {reason}
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              <SettingsPills className="min-w-0 flex-1" />
              {/* Чипы могут перенестись на вторую строку (планшет) — «Создать» остаётся в нижнем углу. */}
              <div className="flex shrink-0 items-center gap-1.5 self-end">
                {mentionButton}
                <RunButton view={view} kind={composer.kind} quote={fresh} labels={labels} onClick={onRun} hideReason />
              </div>
            </div>
          </>
        )}
      </div>

      <input
        ref={fileInput}
        type="file"
        accept={UPLOAD_ACCEPT}
        multiple
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          if (files.length) void addFiles(files, { slot: uploadSlot.current });
        }}
      />

      <ImageGenMini open={imageGen !== null} onClose={() => setImageGen(null)} anchor={boxRef} onCreated={onImageCreated} />
      <CondenseDiffDialog
        open={condense.status === "ready"}
        result={condense.status === "ready" ? condense.result : null}
        labels={labels}
        onAccept={() => finishCondense(true)}
        onKeep={() => finishCondense(false)}
      />
    </div>
  );
}
