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
import { VS_FOCUS, VS_ICON_BTN, VS_LABEL } from "../ui/skin";
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

  // Вид как у VS_INPUT, но на телефоне шрифт 16 px: с меньшим iOS приближает страницу при фокусе.
  const inputCls =
    "w-full rounded-xl border bg-vs-ink/[0.04] px-3 py-2 text-base text-foreground outline-none transition-colors placeholder:text-muted-2 md:text-sm";
  // Цвет рамки — отдельно: у поля с ошибкой он один во всех состояниях.
  const inputLine = "border-vs-ink/10 hover:border-vs-ink/18 focus:border-vs-accent/60";

  return (
    <section className="flex min-w-0 flex-col">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        // Отрицательные поля: зона нажатия 44 px (40 px с 768 px), а строка — высотой с заголовок раздела.
        className={cx(
          "-my-3 flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg text-left md:-my-2.5 md:min-h-10",
          VS_FOCUS,
        )}
      >
        <FiSliders className="size-3.5 shrink-0 text-muted-2" aria-hidden />
        <span className={VS_LABEL}>{tx(t, "settings.advanced")}</span>
        <FiChevronDown
          className={cx(
            "ml-auto size-4 shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      <div
        className={cx(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none",
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        {/* Поля по бокам — чтобы overflow-hidden не срезал кольцо фокуса у кнопок справа. */}
        <div className="-mx-1 min-h-0 overflow-hidden px-1">
          {/* Отступ сверху лежит внутри тела: свёрнутый раздел не оставляет пустой полосы. */}
          <div id={bodyId} className="flex flex-col gap-4 pb-1 pt-4" inert={!open}>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={seedId} className="text-xs font-medium text-foreground/85">
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
                      className={cx(inputCls, "min-h-11 md:min-h-10", seedParsed === "invalid" ? "border-status-fail" : inputLine)}
                    />
                    <button
                      type="button"
                      onClick={() => setSeedNow(Math.floor(Math.random() * SEED_MAX))}
                      title={tx(t, "settings.seedRandom")}
                      aria-label={tx(t, "settings.seedRandom")}
                      className={VS_ICON_BTN}
                    >
                      <FiShuffle className="size-4" aria-hidden />
                    </button>
                    {seedText !== "" && (
                      <button
                        type="button"
                        onClick={() => setSeedNow(undefined)}
                        title={tx(t, "settings.seedClear")}
                        aria-label={tx(t, "settings.seedClear")}
                        className={VS_ICON_BTN}
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
                <label htmlFor={negId} className="text-xs font-medium text-foreground/85">
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
                    className={cx(inputCls, inputLine, "min-h-16 resize-y leading-snug")}
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
