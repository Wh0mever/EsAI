"use client";

import { useId, useState } from "react";
import type { MouseEvent } from "react";
import { FiMinus, FiPlus } from "react-icons/fi";
import { CARD, chip } from "./parts";
import {
  reelSizeExact,
  reelSizeQuick,
  reelSizeStep,
  reelSizeTyped,
  type ReelHint,
  type ReelSize,
} from "./showcaseAdmin";

/**
 * «Роликов в карусели»: сколько роликов показывает первый экран видеостудии.
 * Каждое нажатие сохраняется сразу — отдельной кнопки «Сохранить» нет, как и
 * у остальных правок витрины.
 *
 * Пока запрос в пути, кнопки гаснут через aria-disabled, а поле — через
 * readOnly: настоящий disabled сбрасывает фокус, и с клавиатуры после каждого
 * шага пришлось бы идти к кнопке заново.
 *
 * Число в поле сохраняет Enter. Когда из поля просто ушли, сохраняется только
 * число, годное как есть (showcaseAdmin.reelSizeExact): на телефоне у цифровой
 * клавиатуры Enter нет, а недобранное «4» на пути к «48» записываться пятью
 * не должно — размер сразу уходит на сайт.
 */
type Props = {
  size: ReelSize;
  saving: boolean;
  hint: ReelHint;
  onChange: (value: number) => void;
};

// У края подсказка кнопки объясняет, почему она не нажимается, — указатель ей оставляем.
const STEP_BTN =
  "flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border border-border text-muted transition-colors hover:text-foreground aria-disabled:cursor-not-allowed aria-disabled:opacity-40 aria-disabled:hover:text-muted";
const CHIP_OFF = "aria-disabled:pointer-events-none aria-disabled:opacity-50";

export default function ReelSizeControl({ size, saving, hint, onChange }: Props) {
  const titleId = useId();
  const hintId = useId();

  // Что набрано в поле и ещё не сохранено; null — поле показывает сам размер
  // (в том числе после отката: набранное не должно пережить отказ сервера).
  const [draft, setDraft] = useState<string | null>(null);

  // − и + шагают от числа, которое стоит в поле: набрал 20, нажал «+» — получил 21.
  // Недобранное и число за границей не в счёт — тогда шаг идёт от сохранённого.
  const from = { ...size, value: reelSizeExact(draft, size) ?? size.value };
  const less = reelSizeStep(from, -1);
  const more = reelSizeStep(from, 1);

  const pick = (value: number | null) => {
    setDraft(null);
    if (!saving && value !== null && value !== size.value) onChange(value);
  };

  // Enter (clamp) ставит число за границей на ближнюю; уход из поля — нет, такое число
  // просто пропадает. Пустое поле и не число — «передумал».
  const commit = (clamp: boolean) => {
    if (draft !== null) pick(clamp ? reelSizeTyped(draft, size) : reelSizeExact(draft, size));
  };

  // Пока в поле набранное, нажатие мышью на свою же кнопку фокус из него не уводит.
  // Иначе поле, теряя фокус, сохранило бы набранное раньше, чем дойдёт само нажатие:
  // кнопки на время запроса гаснут, и нажатие пропало бы — сохранилось бы не то число.
  const hold = draft === null ? undefined : (e: MouseEvent) => e.preventDefault();

  return (
    <section aria-labelledby={titleId} className={`${CARD} flex flex-col gap-2 p-3 sm:p-4`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id={titleId} className="text-base font-semibold">
          Роликов в карусели
        </h2>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onMouseDown={hold}
            onClick={() => less !== null && pick(less)}
            aria-disabled={saving || less === null}
            aria-label="На один ролик меньше"
            title={less === null ? `Меньше ${size.min} нельзя` : "Меньше"}
            className={STEP_BTN}
          >
            <FiMinus className="h-4 w-4" aria-hidden />
          </button>
          <input
            value={draft ?? String(size.value)}
            inputMode="numeric"
            maxLength={3}
            readOnly={saving}
            aria-labelledby={titleId}
            aria-describedby={hintId}
            title={`От ${size.min} до ${size.max} — впишите число и нажмите Enter`}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            onBlur={() => commit(false)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit(true);
              if (e.key === "Escape") setDraft(null);
              // Стрелки меняют набранное, как у числового поля; сохраняет по-прежнему Enter.
              if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !saving) {
                e.preventDefault();
                const typed = reelSizeTyped(draft ?? "", size) ?? size.value;
                const next = reelSizeStep({ ...size, value: typed }, e.key === "ArrowUp" ? 1 : -1);
                setDraft(String(next ?? typed));
              }
            }}
            className="h-9 w-12 rounded-lg border border-border bg-surface-2 text-center text-sm font-semibold tabular-nums text-foreground outline-none focus:border-accent read-only:opacity-60"
          />
          <button
            type="button"
            onMouseDown={hold}
            onClick={() => more !== null && pick(more)}
            aria-disabled={saving || more === null}
            aria-label="На один ролик больше"
            title={more === null ? `Больше ${size.max} нельзя` : "Больше"}
            className={STEP_BTN}
          >
            <FiPlus className="h-4 w-4" aria-hidden />
          </button>
        </div>

        <div role="group" aria-label="Роликов в карусели — быстрый выбор" className="flex flex-wrap items-center gap-2">
          {reelSizeQuick(size).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={value === size.value}
              aria-disabled={saving}
              onMouseDown={hold}
              onClick={() => pick(value)}
              className={`${chip(value === size.value)} tabular-nums ${CHIP_OFF}`}
            >
              {value}
            </button>
          ))}
        </div>

        {/* Кнопки − и + своё число не называют: после сохранения его произносит эта строка. */}
        <span role="status" className={saving ? "text-xs text-status-wait" : "sr-only"}>
          {saving ? "Сохраняю…" : `Роликов в карусели: ${size.value}`}
        </span>
      </div>

      <div id={hintId} className="flex flex-col gap-1 text-xs">
        <p className="text-muted-2">{hint.text}</p>
        {hint.note && <p className="text-muted">{hint.note}</p>}
      </div>
    </section>
  );
}
