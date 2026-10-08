"use client";

/**
 * Видеостудия, композер: «✨ Создать картинку» прямо из запроса (§6.4, §9.3).
 *
 * Нет своего фото героя — его можно нарисовать здесь же: короткое описание,
 * модель картинок, пропорции, цена «Создать картинку · 6 кр». Запуск —
 * POST shots/ с kind=image и origin=tray: сервер сразу отдаёт ассет в
 * pending, и в лотке тут же появляется чип «Создаётся…» (а если окно открыли
 * из выбора «@», чип встаёт и в текст). Когда картинка будет готова, чип сам
 * станет обычным @Image N (редьюсер takes/upsert), а на кнопке «Создать» до
 * этого — «Ждём @Image N…».
 *
 * Спишется только за готовую картинку — как и видео. На компьютере — окошко
 * над композером, на телефоне — нижняя шторка.
 */
import { useMemo, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiLoader, FiLock, FiX } from "react-icons/fi";
import { IoSparklesOutline } from "react-icons/io5";
import { aspectHint } from "@/components/ui/AspectIcon";
import { isUid, newClientRequestId, runShot, trackVs } from "@/lib/vstudio/api";
import { errorText, issueText, reactionFor } from "@/lib/vstudio/errors";
import type { AssetJSON, QuoteBody, VsError } from "@/lib/vstudio/types";
import BottomSheet from "../BottomSheet";
import { useVStudio } from "../context";
import { useLocalQuote } from "../hooks/useQuote";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { useIsMobile } from "../settings/SettingsSheet";
import { defaultModel } from "../store";
import { VS_BTN_GOLD, VS_FOCUS, VS_LABEL, vx } from "../ui/skin";
import { OPEN_LIMIT, countOpen, fmtNum, nextRefNumber } from "./composerLogic";
import { ct } from "./composerText";
import { DOCK_FIELD } from "./dockSkin";
import AnchoredPopover from "./Popover";
import { useBalanceRequote } from "./useBalanceRequote";

const PROMPT_MAX = 4000;

/** «9:16 · Вертикальное» — коротко, чтобы влезло в узкий выбор. */
function aspectLabel(t: ReturnType<typeof useTranslation>["t"], ratio: string): string {
  const hint = aspectHint(t, ratio);
  const short = hint && hint !== ratio ? hint.split(/\s[—-]\s/)[0] : "";
  return short ? `${ratio} · ${short}` : ratio;
}

export type ImageGenMiniProps = {
  open: boolean;
  onClose: () => void;
  /** Куда прицепить окошко на компьютере (коробка композера). */
  anchor: RefObject<HTMLElement | null>;
  /** Ассет в pending создан — родитель кладёт чип в лоток (и тег в текст). */
  onCreated: (asset: AssetJSON) => void;
};

type Problem = { text: string; tone: "error" | "info" } | null;

/** Список выбора: подложка непрозрачная — выпадающая часть у браузера берёт цвет отсюда. */
const SELECT =
  "min-h-11 w-full min-w-0 cursor-pointer rounded-xl border border-vs-ink/10 bg-surface-2 px-2.5 text-base text-foreground outline-none transition-colors hover:border-vs-ink/18 focus:border-vs-accent/60 md:min-h-10 md:text-sm";

export default function ImageGenMini({ open, onClose, anchor, onCreated }: ImageGenMiniProps) {
  const mobile = useIsMobile();
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const title = ct(t, "imagegen.title");
  const body = open ? <ImageGenForm onClose={onClose} onCreated={onCreated} /> : null;
  if (mobile) {
    return (
      <BottomSheet open={open} onClose={onClose} title={title} size="auto" zIndex={1045}>
        {body}
      </BottomSheet>
    );
  }
  return (
    <AnchoredPopover anchor={anchor} open={open} onClose={onClose} role="dialog" ariaLabel={title} autoFocus>
      <div className="flex w-[min(24rem,calc(100vw-2rem))] flex-col">
        <div className="flex items-center gap-2 border-b border-vs-ink/10 py-2 pl-4 pr-2">
          <IoSparklesOutline className="text-vs-accent" aria-hidden />
          <h2 className="flex-1 text-sm font-semibold text-foreground">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className={vx(
              "grid size-9 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-vs-ink/[0.08] hover:text-foreground",
              VS_FOCUS,
            )}
            aria-label={ct(t, "imagegen.close")}
          >
            <FiX aria-hidden />
          </button>
        </div>
        <div className="p-4">{body}</div>
      </div>
    </AnchoredPopover>
  );
}

function ImageGenForm({ onClose, onCreated }: { onClose: () => void; onCreated: (asset: AssetJSON) => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions, authed } = useVStudio();
  const models = useMemo(() => state.models?.image ?? [], [state.models]);
  const composer = state.composer;

  const [text, setText] = useState("");
  const [modelId, setModelId] = useState<string | null>(() => {
    if (composer.kind === "image" && composer.model && models.some((m) => m.id === composer.model)) return composer.model;
    return defaultModel(models)?.id ?? null;
  });
  const model = models.find((m) => m.id === modelId) ?? null;
  const aspects = model?.caps.aspect_ratios ?? [];
  const [aspectRaw, setAspect] = useState<string>(() => model?.defaults.aspect_ratio || "auto");
  const aspect = aspectRaw === "auto" || aspects.includes(aspectRaw) ? aspectRaw : "auto";
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const crid = useRef<string | null>(null);

  const prompt = text.trim();
  const chosen = model?.id ?? null;
  const projectUid = isUid(state.project?.uid) ? (state.project?.uid as string) : null;
  const body = useMemo<QuoteBody | null>(
    () =>
      chosen && prompt
        ? { project: projectUid, kind: "image", model: chosen, prompt_text: text, inputs: [], params: { aspect_ratio: aspect } }
        : null,
    [chosen, prompt, text, aspect, projectUid],
  );
  const q = useLocalQuote(body, Boolean(body));
  const quote = q.data;
  const credits = quote?.credits ?? null;
  const errors = quote?.errors ?? [];
  const openImages = countOpen(state.takes.values(), "image");
  const limited = openImages >= OPEN_LIMIT.image;
  const available = quote?.balance?.available;
  const missing = typeof available === "number" && credits != null && available < credits ? Math.ceil(credits - available) : 0;
  const mainSending = state.run.status === "sending";
  const n = nextRefNumber(composer.tray);

  // Баланс пополнили, пока форма открыта (шторка остаётся под окном оплаты): цена несёт старый
  // остаток, и кнопка так и звала бы «Пополнить». Спрашиваем заново, только если не хватало.
  useBalanceRequote(() => {
    if (missing > 0) q.refresh();
  });

  const submit = async () => {
    if (sending || mainSending || !model || !body) return;
    if (!actions.requireAuth()) return;
    if (model.locked) {
      openLockedModel(dispatch, { requireAuth: actions.requireAuth });
      return;
    }
    if (limited) return;
    if (!quote || credits == null || errors.length) {
      if (!quote && !q.loading) q.refresh();
      return;
    }
    if (missing > 0) {
      actions.openTopUp();
      return;
    }
    setSending(true);
    setProblem(null);
    const id = crid.current ?? newClientRequestId();
    crid.current = id;
    trackVs("vstudio_imagegen");
    const res = await runShot({ ...body, quoted_credits: credits, client_request_id: id, origin: "tray" });
    setSending(false);
    if (res.ok) {
      crid.current = null;
      dispatch({ type: "run/done", response: res.data });
      const asset = res.data.asset ?? res.data.take.result;
      if (asset) onCreated(asset);
      actions.refreshBalance();
      setText("");
      onClose();
      return;
    }
    const err: VsError = res.error;
    // Нет ответа — запрос мог дойти: следующий клик уйдёт с тем же id и не создаст второй картинки.
    if (err.status !== 0) crid.current = null;
    const r = reactionFor(err);
    switch (r.kind) {
      case "paywall":
        actions.handleError(err);
        trackVs("vstudio_paywall");
        break;
      case "requote":
        q.refresh();
        setProblem({ text: errorText(t, err), tone: "info" });
        break;
      case "blocked":
        q.refresh();
        break;
      case "limit":
        setProblem({ text: ct(t, "imagegen.limit", { n: r.limit ?? OPEN_LIMIT.image }), tone: "error" });
        break;
      default:
        actions.handleError(err, { silent: true });
        if (r.kind !== "auth" && r.kind !== "disabled" && r.kind !== "ignore") setProblem({ text: errorText(t, err), tone: "error" });
    }
  };

  if (!models.length) {
    return <p className="py-2 text-sm text-muted">{ct(t, "imagegen.noModels")}</p>;
  }

  const runLabel =
    missing > 0
      ? ct(t, "composer.topup", { n: fmtNum(missing) })
      : credits != null
        ? ct(t, "imagegen.run", { credits: fmtNum(credits) })
        : ct(t, "imagegen.runNoPrice");
  const disabled = sending || mainSending || !prompt || limited || (quote != null && errors.length > 0);

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, PROMPT_MAX))}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing || e.keyCode === 229) return;
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        rows={3}
        maxLength={PROMPT_MAX}
        placeholder={ct(t, "imagegen.placeholder")}
        aria-label={ct(t, "imagegen.title")}
        className={`${DOCK_FIELD} min-h-[5.5rem] resize-y px-3 py-2 leading-relaxed caret-vs-accent`}
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className={VS_LABEL}>{ct(t, "imagegen.model")}</span>
          <select
            value={modelId ?? ""}
            onChange={(e) => setModelId(e.target.value)}
            className={SELECT}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {typeof m.per_image === "number"
                  ? ` · ${String(t("settings.credits", { n: fmtNum(m.per_image), defaultValue: "{{n}} кр" }))}`
                  : ""}
                {m.locked ? ` · ${ct(t, "imagegen.locked")}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className={VS_LABEL}>{ct(t, "imagegen.aspect")}</span>
          <select
            value={aspect}
            onChange={(e) => setAspect(e.target.value)}
            className={SELECT}
          >
            <option value="auto">{ct(t, "imagegen.aspectAuto")}</option>
            {aspects.map((a) => (
              <option key={a} value={a}>
                {aspectLabel(t, a)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-muted">{ct(t, "imagegen.note", { n })}</p>
      {(errors.length > 0 || problem || limited) && (
        <ul className="flex flex-col gap-1" aria-live="polite">
          {limited && (
            <li className="flex gap-1.5 text-xs text-status-fail">
              <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden />
              {ct(t, "imagegen.limit", { n: openImages })}
            </li>
          )}
          {errors.map((e, i) => (
            <li key={`${e.code}:${i}`} className="flex gap-1.5 text-xs text-status-fail">
              <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden />
              {issueText(t, e, "errors")}
            </li>
          ))}
          {problem && (
            <li className={`flex gap-1.5 text-xs ${problem.tone === "error" ? "text-status-fail" : "text-muted"}`}>
              <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden />
              {problem.text}
            </li>
          )}
        </ul>
      )}
      <button
        type="submit"
        disabled={disabled}
        aria-busy={sending || q.loading || undefined}
        className={`${VS_BTN_GOLD} w-full md:!min-h-11`}
      >
        {sending ? (
          <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden />
        ) : model?.locked ? (
          <FiLock aria-hidden />
        ) : (
          <IoSparklesOutline aria-hidden />
        )}
        <span className={q.loading && prompt ? "opacity-70" : ""}>{runLabel}</span>
      </button>
      {authed !== false && <p className="-mt-1 text-center text-[11px] text-muted-2">{ct(t, "price.note")}</p>}
    </form>
  );
}
