"use client";

import { memo, useRef, useState, type Dispatch, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  FiAlertTriangle,
  FiCornerDownRight,
  FiEdit2,
  FiLoader,
  FiPlusCircle,
  FiRefreshCw,
  FiShare2,
  FiShuffle,
  FiX,
} from "react-icons/fi";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import ShareButtons from "@/components/ui/ShareButtons";
import { assetFromTake, newClientRequestId, quote, retryShot, shareVideo, trackVs } from "@/lib/vstudio/api";
import { errorText, issueText, reactionFor } from "@/lib/vstudio/errors";
import type {
  AssetJSON,
  CompilerIssue,
  InputSlot,
  ModelJSON,
  QuoteJSON,
  ShotJSON,
  TakeLite,
  TrayItem,
  VsAction,
  VsError,
} from "@/lib/vstudio/types";
import { openModelPicker } from "../settings/ModelPicker";
import { mediaFilename, retryBlock } from "./feedLogic";

/** Что карточка положила в композер — родитель может сфокусировать редактор или открыть шторку. */
export type ComposerFillReason = "edit" | "other_model" | "first_frame" | "reference" | "example";

export type ShotActionsProps = {
  shot: ShotJSON;
  /** Показанный в карусели дубль. */
  take: TakeLite | null;
  /** Все дубли кадра: «Повторить» прячется, пока хоть один идёт. */
  takes: TakeLite[];
  /** Модель кадра в каталоге: null — её больше нет, undefined — каталог не загружен. */
  model: ModelJSON | null | undefined;
  dispatch: Dispatch<VsAction>;
  onComposerFilled?: (reason: ComposerFillReason) => void;
};

type Tr = (k: string, o?: Record<string, unknown>) => string;

type RetryState =
  | { phase: "idle" }
  | { phase: "quoting" }
  | {
      phase: "confirm" | "sending";
      credits: number | null;
      quote: QuoteJSON | null;
      errors: CompilerIssue[];
      /** «Цена изменилась…» после 409 price_changed. */
      note: string;
    }
  | { phase: "error"; message: string };

/** video — ссылка на ролик, для которого состояние: карусель могла уйти на другой дубль. */
type ShareState =
  | { phase: "idle" }
  | { phase: "loading"; video: string }
  | { phase: "ready"; video: string; url: string }
  | { phase: "error"; video: string; message: string };

/**
 * 409 price_changed: новая цена приходит без нового quote — «останется N кр»
 * пересчитываем от свободного остатка, чтобы строка не показывала старую сумму.
 */
function withCredits(q: QuoteJSON | null, credits: number | null): QuoteJSON | null {
  if (!q || credits == null) return q;
  const b = q.balance;
  const balance = b ? { ...b, after: Math.max(0, b.available - credits) } : b;
  return { ...q, credits, balance };
}

let lidSeq = 0;
/** Локальный id чипа лотка для материала из ленты. */
function feedLid(asset: string): string {
  lidSeq += 1;
  return `feed-${asset.slice(0, 8)}-${lidSeq}`;
}

function trayItem(asset: AssetJSON, slot: InputSlot): TrayItem {
  return {
    lid: feedLid(asset.uid),
    assetUid: asset.uid,
    slot,
    role: "",
    included: true,
    status: asset.status === "ready" ? "ready" : asset.status === "failed" ? "failed" : "pending",
    progress: 100,
    preview: asset.thumb_url || asset.url,
    asset,
  };
}

function Btn({
  onClick,
  disabled,
  busy,
  icon,
  label,
  primary,
  compact,
  title,
}: {
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  icon: ReactNode;
  label: string;
  primary?: boolean;
  /** На телефоне только значок (подпись — в aria-label и title). */
  compact?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      aria-label={compact ? label : undefined}
      title={title || label}
      className={`inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1.5 rounded-xl px-2.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-9 sm:min-w-0 ${
        primary
          ? "bg-accent text-on-accent hover:bg-accent-strong"
          : "border border-border bg-surface text-foreground hover:border-accent/60 hover:bg-surface-2"
      }`}
    >
      <span className="text-sm" aria-hidden>
        {busy ? <FiLoader className="animate-spin" /> : icon}
      </span>
      <span className={compact ? "hidden sm:inline" : ""}>{label}</span>
    </button>
  );
}

/**
 * Действия карточки (§9.6): Повторить (новый дубль того же кадра после
 * нового quote — цену человек видит до оплаты), Изменить и Другая модель
 * (композер заполняется кадром), Скачать, Поделиться, «Последний кадр →
 * первый», «В референсы». «Повторить» нет, пока хоть один дубль кадра идёт:
 * заплатить дважды за ещё снимающийся нельзя.
 */
function ShotActions({ shot, take, takes, model, dispatch, onComposerFilled }: ShotActionsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tr = t as unknown as Tr;
  const [retry, setRetry] = useState<RetryState>({ phase: "idle" });
  const [share, setShare] = useState<ShareState>({ phase: "idle" });
  const [frameBusy, setFrameBusy] = useState(false);
  // Один client_request_id на попытку оплаты: живёт до ответа сервера, двойной клик не платит дважды.
  const cridRef = useRef<string | null>(null);

  const result = take?.status === "done" ? take.result : null;
  const block = retryBlock(shot, takes, model);
  const isVideo = shot.kind === "video";

  const toast = (tone: "ok" | "error" | "info", text: string) =>
    dispatch({ type: "ui/toast", toast: { id: `vs-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, tone, text } });

  /** Ошибка API → пэйволл или окно входа (null — уже показано окном) либо текст для карточки. */
  const routeError = (err: VsError): string | null => {
    const r = reactionFor(err);
    if (r.kind === "ignore") return null;
    if (r.kind === "paywall") {
      // Воронку шлёт тот, кто запускал (контекст студии её не дублирует).
      trackVs("vstudio_paywall");
      dispatch({ type: "ui/paywall", paywall: r.paywall });
      return null;
    }
    if (r.kind === "auth") {
      trackVs("vstudio_auth_prompt");
      dispatch({ type: "ui/auth", open: true });
      return null;
    }
    if (r.kind === "disabled") dispatch({ type: "page/status", status: "disabled" });
    return errorText(t, err);
  };

  /* ---------- Повторить ---------- */

  const startRetry = async () => {
    if (block) return;
    if (model?.locked) {
      // Бесплатный тариф и премиальная модель: сразу пэйволл, без лишнего quote.
      trackVs("vstudio_paywall");
      dispatch({ type: "ui/paywall", paywall: { reason: "premium_locked" } });
      return;
    }
    setRetry({ phase: "quoting" });
    const res = await quote({ shot: shot.uid });
    if (!res.ok) {
      const msg = routeError(res.error);
      setRetry(msg ? { phase: "error", message: msg } : { phase: "idle" });
      return;
    }
    setRetry({ phase: "confirm", credits: res.data.credits, quote: res.data, errors: res.data.errors || [], note: "" });
  };

  const confirmRetry = async () => {
    if (retry.phase !== "confirm" || retry.credits == null || retry.errors.length) return;
    const credits = retry.credits;
    const q = retry.quote;
    cridRef.current = cridRef.current || newClientRequestId();
    setRetry({ ...retry, phase: "sending" });
    const res = await retryShot(shot.uid, { quoted_credits: credits, client_request_id: cridRef.current });
    if (res.ok) {
      cridRef.current = null;
      dispatch({ type: "take/added", shot: shot.uid, take: res.data.take });
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        /* шапка обновит баланс сама при следующем запросе */
      }
      setRetry({ phase: "idle" });
      return;
    }
    const err = res.error;
    const r = reactionFor(err);
    // Ответа нет (сеть, 5xx): тот же id на следующий клик — сервер вернёт уже созданный дубль.
    if (r.kind !== "offline" && r.kind !== "retry_later") cridRef.current = null;
    if (r.kind === "requote") {
      setRetry({
        phase: "confirm",
        credits: r.credits,
        quote: withCredits(q, r.credits),
        errors: [],
        note: errorText(t, err),
      });
      return;
    }
    if (r.kind === "blocked") {
      setRetry({ phase: "confirm", credits, quote: q, errors: r.errors, note: "" });
      return;
    }
    const msg = routeError(err);
    setRetry(msg ? { phase: "error", message: msg } : { phase: "idle" });
  };

  const cancelRetry = () => {
    cridRef.current = null;
    setRetry({ phase: "idle" });
  };

  /* ---------- Композер ---------- */

  const edit = () => {
    dispatch({ type: "composer/fill", shot });
    onComposerFilled?.("edit");
  };

  const otherModel = () => {
    dispatch({ type: "composer/fill", shot });
    dispatch({ type: "ui/panel", panel: "settings", open: true });
    // Сразу раскрыть список моделей (на телефоне ждёт, пока смонтируется шторка).
    openModelPicker();
    onComposerFilled?.("other_model");
  };

  const lastFrame = async () => {
    if (!take || frameBusy) return;
    setFrameBusy(true);
    const res = await assetFromTake(take.uid);
    setFrameBusy(false);
    if (!res.ok) {
      const msg = routeError(res.error);
      if (msg) toast("error", msg);
      return;
    }
    dispatch({ type: "library/upsert", asset: res.data });
    // Кадр продолжает ролик: у картинки слота кадров нет, поэтому композер — на «Видео»
    // (если он уже там, редьюсер ничего не меняет).
    dispatch({ type: "composer/kind", kind: "video" });
    dispatch({ type: "tray/add", item: trayItem(res.data, "first_frame") });
    toast("ok", t("toast.frameAdded", { defaultValue: "Последний кадр стал первым кадром нового запроса" }));
    onComposerFilled?.("first_frame");
  };

  const asReference = () => {
    if (!result) return;
    dispatch({ type: "tray/add", item: trayItem(result, "reference") });
    toast("ok", t("toast.refAdded", { defaultValue: "Картинка добавлена в запрос" }));
    onComposerFilled?.("reference");
  };

  /* ---------- Поделиться ---------- */

  const startShare = async () => {
    const video = result?.url;
    if (!video) return;
    if (share.phase === "ready" && share.video === video) {
      setShare({ phase: "idle" });
      return;
    }
    setShare({ phase: "loading", video });
    const res = await shareVideo(video, { prompt: shot.prompt_text, model: shot.model?.name || "" });
    if (!res.ok || !res.data.share_url) {
      const msg = res.ok ? errorText(t, { code: "unknown", message: "" }) : routeError(res.error);
      setShare(msg ? { phase: "error", video, message: msg } : { phase: "idle" });
      return;
    }
    trackVs("vstudio_share");
    setShare({ phase: "ready", video, url: res.data.share_url });
  };
  // Панель и ошибка «Поделиться» — только у того ролика, для которого их получили.
  const shareHere = share.phase !== "idle" && share.video === result?.url ? share : null;

  /* ---------- Разметка ---------- */

  const retryLabel = t("run.actions.retry", { defaultValue: "Повторить" });
  const confirming = retry.phase === "confirm" || retry.phase === "sending";
  const balance = confirming ? retry.quote?.balance ?? null : null;
  const missing =
    confirming && retry.credits != null && balance && balance.available < retry.credits
      ? retry.credits - balance.available
      : 0;
  const retryWarnings = confirming ? (retry.quote?.warnings || []).slice(0, 2) : [];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {block !== "open" && !confirming && (
          <Btn
            onClick={() => void startRetry()}
            busy={retry.phase === "quoting"}
            disabled={block === "model"}
            icon={<FiRefreshCw />}
            label={retryLabel}
          />
        )}
        <Btn onClick={edit} icon={<FiEdit2 />} label={t("run.actions.edit", { defaultValue: "Изменить" })} />
        <Btn
          onClick={otherModel}
          icon={<FiShuffle />}
          label={t("run.actions.otherModel", { defaultValue: "Другая модель" })}
          compact
        />
        {result?.url && (
          <SaveMediaButton
            url={result.url}
            filename={mediaFilename(result)}
            label={t("run.actions.download", { defaultValue: "Скачать" })}
            className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-border bg-surface px-2.5 text-xs font-medium text-foreground transition-colors hover:border-accent/60 hover:bg-surface-2 sm:min-h-9 sm:min-w-0"
            iconClassName="text-sm"
          >
            <span className="hidden sm:inline">{t("run.actions.download", { defaultValue: "Скачать" })}</span>
          </SaveMediaButton>
        )}
        {result?.url && isVideo && (
          <Btn
            onClick={() => void startShare()}
            busy={shareHere?.phase === "loading"}
            icon={<FiShare2 />}
            label={t("run.actions.share", { defaultValue: "Поделиться" })}
            compact
          />
        )}
        {result && isVideo && (
          <Btn
            onClick={() => void lastFrame()}
            busy={frameBusy}
            icon={<FiCornerDownRight />}
            label={t("run.actions.lastFrame", { defaultValue: "Последний кадр → первый" })}
            compact
          />
        )}
        {result && !isVideo && (
          <Btn
            onClick={asReference}
            icon={<FiPlusCircle />}
            label={t("run.actions.asReference", { defaultValue: "В референсы" })}
            compact
          />
        )}
      </div>

      {block === "model" && (
        <p className="text-xs text-muted">
          {t("run.modelGone", { defaultValue: "Этой модели больше нет в студии — нажмите «Другая модель»." })}
        </p>
      )}

      {confirming && (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface-2 p-3" role="group" aria-label={retryLabel}>
          {retry.note && <p className="text-xs text-status-wait">{retry.note}</p>}
          {retry.errors.length > 0 ? (
            <>
              <p className="flex items-start gap-2 text-sm text-foreground">
                <FiAlertTriangle className="mt-0.5 shrink-0 text-status-fail" aria-hidden />
                <span>{issueText(t, retry.errors[0], "errors")}</span>
              </p>
              <p className="text-xs text-muted">
                {t("run.retryBlocked", { defaultValue: "Повторить как есть нельзя — нажмите «Изменить» и поправьте запрос." })}
              </p>
            </>
          ) : retry.credits == null ? (
            <p className="text-sm text-foreground">
              {t("run.retryNoPrice", { defaultValue: "Не получилось посчитать цену. Нажмите «Изменить» и проверьте параметры." })}
            </p>
          ) : (
            <>
              {retryWarnings.map((w, k) => (
                <p key={`${w.code}-${k}`} className="flex items-start gap-2 text-xs text-status-wait">
                  <FiAlertTriangle className="mt-0.5 shrink-0" aria-hidden />
                  <span>{issueText(t, w, "warnings")}</span>
                </p>
              ))}
              <p className="text-xs text-muted">
                {t("price.note", { defaultValue: "Спишется только за готовый результат" })}
                {balance && balance.after != null && missing === 0
                  ? ` · ${tr("run.retryAfter", { defaultValue: "останется {{n}} кр", n: balance.after })}`
                  : ""}
              </p>
            </>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {retry.errors.length === 0 && retry.credits != null && (
              missing > 0 ? (
                <Btn
                  primary
                  onClick={() => dispatch({ type: "ui/topup", open: true })}
                  icon={<FiPlusCircle />}
                  label={t("composer.topup", { defaultValue: "Пополнить · не хватает {{n}} кр", n: missing })}
                />
              ) : (
                <Btn
                  primary
                  onClick={() => void confirmRetry()}
                  busy={retry.phase === "sending"}
                  icon={<FiRefreshCw />}
                  label={t("run.actions.retryConfirm", {
                    defaultValue: "Повторить · {{credits}} кр",
                    credits: retry.credits,
                  })}
                />
              )
            )}
            {retry.errors.length > 0 && (
              <Btn onClick={edit} icon={<FiEdit2 />} label={t("run.actions.edit", { defaultValue: "Изменить" })} />
            )}
            <Btn
              onClick={cancelRetry}
              disabled={retry.phase === "sending"}
              icon={<FiX />}
              label={t("run.actions.retryCancel", { defaultValue: "Не надо" })}
            />
          </div>
        </div>
      )}

      {retry.phase === "error" && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-status-fail" role="alert">
          {retry.message}
          <button
            type="button"
            onClick={() => setRetry({ phase: "idle" })}
            className="cursor-pointer rounded-md px-1.5 py-0.5 text-muted hover:text-foreground"
            aria-label={t("run.actions.dismiss", { defaultValue: "Скрыть" })}
          >
            <FiX aria-hidden />
          </button>
        </p>
      )}

      {shareHere?.phase === "ready" && (
        <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface-2 p-3">
          <p className="text-xs text-muted">
            {t("share.hint", { defaultValue: "Ссылка на страницу ролика — видео откроется прямо в мессенджере" })}
          </p>
          <ShareButtons
            url={shareHere.url}
            text={t("share.text", { defaultValue: "Смотрите, что получилось в Видеостудии EsAI" })}
            compact
          />
        </div>
      )}
      {shareHere?.phase === "error" && (
        <p className="text-xs text-status-fail" role="alert">
          {shareHere.message}
        </p>
      )}
    </div>
  );
}

export default memo(ShotActions);
