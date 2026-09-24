"use client";

/**
 * «Дополнительно»: seed и негативный промпт.
 *
 * Негатив — только если модель его понимает (caps.negative; сервер шлёт его
 * через passthrough провайдера). Seed — если caps.seed. Что не поддерживается —
 * не поле, а строка с причиной.
 *
 * Ввод идёт в черновик и уходит в стор с паузой: каждое изменение параметров
 * сразу перезапрашивает цену (useQuote), и запрос на каждую букву ни к чему.
 * Потеря фокуса или закрытие панели досылают черновик сразу. Смена модели
 * или вида сначала забирает черновик (useRunSettingsSync.takeParamsDraft) —
 * он входит в выбор новой модели, а не догоняет его устаревшим патчем.
 */
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiShuffle, FiSliders, FiX } from "react-icons/fi";
import type { ModelJSON, ShotParams, VsKind } from "@/lib/vstudio/types";
import { Reason, Section, cx } from "./SettingsBits";
import { NEGATIVE_MAX, SEED_MAX } from "./settingsModel";
import { fmtNum, tx } from "./settingsText";
import { registerParamsDraft } from "./useRunSettingsSync";

export type AdvancedSectionProps = {
  model: ModelJSON;
  kind: VsKind;
  params: ShotParams;
  onChange: (patch: Partial<ShotParams>) => void;
};

const TYPE_PAUSE_MS = 450;

type Draft = Partial<ShotParams>;

function parseSeed(text: string): number | null | "invalid" {
  if (text === "") return null;
  if (!/^\d{1,10}$/.test(text)) return "invalid";
  const n = Number(text);
  return n <= SEED_MAX ? n : "invalid";
}

export default function AdvancedSection({ model, kind, params, onChange }: AdvancedSectionProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const seedOn = model.caps.seed;
  const negOn = kind === "video" && model.caps.negative;
  const [open, setOpen] = useState(() => params.seed != null || !!params.negative_prompt);
  const [seedDraft, setSeedDraft] = useState<string | null>(null);
  const [negDraft, setNegDraft] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Накопленный патч: seed и негатив, набранные подряд, уходят вместе. */
  const pendingRef = useRef<Draft | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  const bodyId = useId();
  const seedId = useId();
  const seedHintId = useId();
  const negId = useId();

  const take = (): Draft | null => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const patch = pendingRef.current;
    pendingRef.current = null;
    return patch;
  };
  const flush = () => {
    const patch = take();
    if (patch) onChangeRef.current(patch);
  };
  const schedule = (patch: Draft) => {
    pendingRef.current = { ...(pendingRef.current || {}), ...patch };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, TYPE_PAUSE_MS);
  };
  const drop = (key: keyof ShotParams) => {
    if (pendingRef.current && key in pendingRef.current) delete pendingRef.current[key];
  };

  useEffect(() => {
    const unregister = registerParamsDraft(take);
    return () => {
      unregister();
      // Панель закрыли посреди ввода — досылаем, чтобы набранное не пропало.
      flush();
    };
    // Регистрация одна на жизнь раздела; take и flush работают через ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!seedOn && !negOn) {
    return (
      <Section title={tx(t, "settings.advanced")} icon={<FiSliders />}>
        <Reason tone="muted">{tx(t, "settings.advancedNone", { model: model.name })}</Reason>
      </Section>
    );
  }

  const seedText = seedDraft ?? (params.seed != null ? String(params.seed) : "");
  const seedParsed = parseSeed(seedText);
  const setSeedText = (raw: string) => {
    const v = raw.replace(/\s+/g, "");
    setSeedDraft(v);
    const parsed = parseSeed(v);
    // Кривое значение не отправляем — и прежнее ещё не ушедшее тоже.
    if (parsed === "invalid") {
      drop("seed");
      return;
    }
    schedule({ seed: parsed ?? undefined });
  };
  const setSeedNow = (seed: number | undefined) => {
    setSeedDraft(null);
    drop("seed");
    onChange({ seed });
  };

  const negText = negDraft ?? params.negative_prompt ?? "";
  const setNegText = (v: string) => {
    const text = v.slice(0, NEGATIVE_MAX);
    setNegDraft(text);
    schedule({ negative_prompt: text.trim() ? text : undefined });
  };

  const inputCls =
    "w-full rounded-xl border border-border bg-surface px-3 py-2 text-base text-foreground outline-none transition-colors placeholder:text-muted-2 focus:border-accent md:text-sm";

  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex min-h-10 items-center gap-1.5 text-left cursor-pointer"
      >
        <FiSliders className="size-3.5 text-muted-2" aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{tx(t, "settings.advanced")}</span>
        <FiChevronDown className={cx("ml-auto size-4 text-muted transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>

      <div
        className={cx(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out",
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div id={bodyId} className="flex flex-col gap-4 pb-1" inert={!open}>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={seedId} className="text-xs font-medium text-foreground">
                {tx(t, "settings.seed")}
              </label>
              {seedOn ? (
                <>
                  <div className="flex items-center gap-1.5">
                    <input
                      id={seedId}
                      type="text"
                      inputMode="numeric"
                      autoComplete="off"
                      value={seedText}
                      placeholder={tx(t, "settings.seedPlaceholder")}
                      aria-invalid={seedParsed === "invalid"}
                      aria-describedby={seedHintId}
                      onChange={(e) => setSeedText(e.target.value)}
                      onBlur={() => {
                        flush();
                        if (parseSeed(seedDraft ?? "") !== "invalid") setSeedDraft(null);
                      }}
                      className={cx(inputCls, seedParsed === "invalid" && "border-status-fail focus:border-status-fail")}
                    />
                    <button
                      type="button"
                      onClick={() => setSeedNow(Math.floor(Math.random() * SEED_MAX))}
                      title={tx(t, "settings.seedRandom")}
                      aria-label={tx(t, "settings.seedRandom")}
                      className="grid size-11 shrink-0 place-items-center rounded-xl border border-border text-muted hover:border-border-strong hover:text-foreground md:size-10 cursor-pointer"
                    >
                      <FiShuffle className="size-4" aria-hidden />
                    </button>
                    {seedText !== "" && (
                      <button
                        type="button"
                        onClick={() => setSeedNow(undefined)}
                        title={tx(t, "settings.seedClear")}
                        aria-label={tx(t, "settings.seedClear")}
                        className="grid size-11 shrink-0 place-items-center rounded-xl border border-border text-muted hover:border-border-strong hover:text-foreground md:size-10 cursor-pointer"
                      >
                        <FiX className="size-4" aria-hidden />
                      </button>
                    )}
                  </div>
                  <div id={seedHintId}>
                    {seedParsed === "invalid" ? (
                      <Reason tone="error">{tx(t, "settings.seedInvalid", { max: fmtNum(SEED_MAX) })}</Reason>
                    ) : (
                      <Reason tone="muted">{tx(t, "settings.seedHint")}</Reason>
                    )}
                  </div>
                </>
              ) : (
                <Reason>{tx(t, "settings.seedUnsupported", { model: model.name })}</Reason>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline gap-2">
                <label htmlFor={negId} className="text-xs font-medium text-foreground">
                  {tx(t, "settings.negative")}
                </label>
                {negOn && (
                  <span className="ml-auto text-[10px] tabular-nums text-muted-2">
                    {tx(t, "settings.negativeCount", { n: fmtNum(negText.length), max: fmtNum(NEGATIVE_MAX) })}
                  </span>
                )}
              </div>
              {negOn ? (
                <>
                  <textarea
                    id={negId}
                    rows={2}
                    value={negText}
                    maxLength={NEGATIVE_MAX}
                    placeholder={tx(t, "settings.negativePlaceholder")}
                    onChange={(e) => setNegText(e.target.value)}
                    onBlur={() => {
                      flush();
                      setNegDraft(null);
                    }}
                    className={cx(inputCls, "min-h-16 resize-y")}
                  />
                  <Reason tone="muted">{tx(t, "settings.negativeHint")}</Reason>
                </>
              ) : (
                <Reason>{tx(t, "settings.negativeUnsupported", { model: model.name })}</Reason>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
