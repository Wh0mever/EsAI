"use client";

/**
 * Видеостудия, композер: счётчик длины промпта под полем (§4.8, §0 п. 10).
 *
 * «2 940 симв. · ~480 слов · Seedance лучше понимает до ~150 слов». Считает
 * мгновенно на клиенте, свежий quote подтверждает (сервер считает
 * сериализованный текст — с заголовком ролей и тегами модели). Серый — всё
 * хорошо, жёлтый — длиннее мягкого лимита модели (кнопка «Сжать с ИИ»),
 * красный — длиннее жёсткого: «Создать» выключена с причиной. Текст не
 * обрезается нигде.
 */
import { useTranslation } from "react-i18next";
import { IoSparklesOutline } from "react-icons/io5";
import { FiLoader } from "react-icons/fi";
import type { MeterView } from "./composerLogic";
import { fmtNum } from "./composerLogic";
import { ct } from "./composerText";

export type PromptMeterProps = {
  meter: MeterView;
  modelName: string;
  /** «Сжать с ИИ» (null — нечего сжимать или гость). */
  onCondense: (() => void) | null;
  condensing?: boolean;
};

export default function PromptMeter({ meter, modelName, onCondense, condensing }: PromptMeterProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  if (meter.chars === 0) return null;
  const { level } = meter;
  const color = level === "hard" ? "text-status-fail" : level === "soft" ? "text-status-wait" : "text-muted";
  const bar = level === "hard" ? "bg-status-fail" : level === "soft" ? "bg-status-wait" : "bg-muted-2";
  const fill = Math.max(4, Math.min(100, Math.round(meter.ratio * 100)));
  const note =
    level === "hard"
      ? ct(t, "meter.hard", { model: modelName, n: fmtNum(meter.hard) })
      : level === "soft" && meter.soft
        ? ct(t, "meter.soft", { model: modelName, n: fmtNum(meter.soft) })
        : "";
  return (
    <div className={`flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs ${color}`} aria-live="polite">
      <span className="tabular-nums">{ct(t, "meter.chars", { n: fmtNum(meter.chars) })}</span>
      <span aria-hidden>·</span>
      <span className="tabular-nums">{ct(t, "meter.words", { n: fmtNum(meter.words) })}</span>
      <span className="relative h-1.5 w-12 overflow-hidden rounded-full bg-surface-3" aria-hidden>
        <span className={`absolute inset-y-0 left-0 rounded-full ${bar}`} style={{ width: `${fill}%` }} />
      </span>
      {note && <span className="min-w-0">{note}</span>}
      {level !== "ok" && onCondense && (
        <button
          type="button"
          onClick={onCondense}
          disabled={condensing}
          className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-current/40 px-2 font-semibold text-foreground transition-colors hover:bg-surface-2 disabled:cursor-wait disabled:opacity-70 max-md:min-h-11 cursor-pointer"
        >
          {condensing ? <FiLoader className="animate-spin" aria-hidden /> : <IoSparklesOutline aria-hidden />}
          {condensing ? ct(t, "assist.working") : ct(t, "meter.condense")}
        </button>
      )}
    </div>
  );
}
