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
import { VS_FOCUS, vx } from "../ui/skin";
import type { MeterView } from "./composerLogic";
import { fmtNum } from "./composerLogic";
import { ct } from "./composerText";

export type PromptMeterProps = {
  meter: MeterView;
  modelName: string;
  /** «Сжать с ИИ» (null — нечего сжимать или гость). */
  onCondense: (() => void) | null;
  condensing?: boolean;
  /** Строка-разделитель панели запроса на компьютере: мельче и прижата вправо. */
  compact?: boolean;
};

export default function PromptMeter({ meter, modelName, onCondense, condensing, compact }: PromptMeterProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  if (meter.chars === 0) return null;
  const { level } = meter;
  const color = level === "hard" ? "text-status-fail" : level === "soft" ? "text-status-wait" : compact ? "text-muted-2" : "text-muted";
  const bar = level === "hard" ? "bg-status-fail" : level === "soft" ? "bg-status-wait" : "bg-vs-ink/35";
  const fill = Math.max(4, Math.min(100, Math.round(meter.ratio * 100)));
  const note =
    level === "hard"
      ? ct(t, "meter.hard", { model: modelName, n: fmtNum(meter.hard) })
      : level === "soft" && meter.soft
        ? ct(t, "meter.soft", { model: modelName, n: fmtNum(meter.soft) })
        : "";
  return (
    <div
      className={vx("flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1", compact ? "justify-end text-[11px]" : "text-xs", color)}
      aria-live="polite"
    >
      <span className="tabular-nums">{ct(t, "meter.chars", { n: fmtNum(meter.chars) })}</span>
      <span aria-hidden>·</span>
      <span className="tabular-nums">{ct(t, "meter.words", { n: fmtNum(meter.words) })}</span>
      <span className="relative h-1 w-12 overflow-hidden rounded-full bg-vs-ink/10" aria-hidden>
        <span className={`absolute inset-y-0 left-0 rounded-full ${bar}`} style={{ width: `${fill}%` }} />
      </span>
      {note && <span className="min-w-0">{note}</span>}
      {level !== "ok" && onCondense && (
        <button
          type="button"
          onClick={onCondense}
          disabled={condensing}
          className={vx(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-current/40 px-3 text-xs font-semibold text-foreground transition-colors hover:bg-vs-ink/[0.08] disabled:cursor-wait disabled:opacity-70 max-md:min-h-11",
            compact ? "min-h-8" : "min-h-9",
            VS_FOCUS,
          )}
        >
          {condensing ? <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden /> : <IoSparklesOutline aria-hidden />}
          {condensing ? ct(t, "assist.working") : ct(t, "meter.condense")}
        </button>
      )}
    </div>
  );
}
