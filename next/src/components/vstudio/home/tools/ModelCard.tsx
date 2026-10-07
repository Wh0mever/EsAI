"use client";

import { memo } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowRight, FiCheck, FiClock, FiLock } from "react-icons/fi";
import { vendorColorByOpenRouterId, vendorInitialByOpenRouterId, vendorLabelByOpenRouterId } from "@/lib/vendorColors";
import type { ModelJSON, VsKind } from "@/lib/vstudio/types";
import { etaText } from "../../settings/settingsModel";
import { tx, txRef } from "../../settings/settingsText";
import { VS_ON_MEDIA, VS_TAG, VS_TAG_GOLD, vx } from "../../ui/skin";
import { HOME_CARD, HOME_CARD_ON } from "./cardSkin";
import { artLens, stripFacts, stripPrice, vendorArt } from "./modelStrip";

export type ModelCardProps = {
  model: ModelJSON;
  kind: VsKind;
  /** Эта модель сейчас стоит в панели запроса. */
  selected: boolean;
  onPick: (model: ModelJSON) => void;
};

/** Кольца «объектива»: одна точка, три окружности вокруг неё. */
const RING = "absolute left-0 top-0 -translate-x-1/2 -translate-y-1/2 rounded-full border";

/**
 * Карточка модели в ленте первого экрана. Шапка — не кадр и не логотип, а
 * рисунок из цвета вендора: карточка модели не показывает съёмку, которую
 * эта модель не делала (§0.6). Под шапкой — то же, что в списке моделей
 * панели параметров, только коротко: три метки, цена и состояние.
 */
function ModelCard({ model, kind, selected, onPick }: ModelCardProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const facts = stripFacts(model, kind);
  const price = stripPrice(model, kind);
  const eta = etaText(model.eta_s);
  const lens = artLens(model.id);

  return (
    <button
      type="button"
      onClick={() => onPick(model)}
      aria-pressed={selected}
      className={vx(selected ? HOME_CARD_ON : HOME_CARD, "group/model")}
    >
      {/* Скругление на пиксель меньше карточки: шапка лежит внутри её рамки. */}
      <span
        className="vs-grain relative block h-24 w-full shrink-0 overflow-hidden rounded-t-[15px] border-b border-white/[0.06] bg-surface-2"
        style={{ background: vendorArt(vendorColorByOpenRouterId(model.id)) }}
      >
        <span aria-hidden className="absolute size-0" style={{ left: `${lens.x}%`, top: `${lens.y}%` }}>
          <span
            className={vx(
              RING,
              "size-14 border-white/[0.11] transition-transform duration-700 ease-[var(--vs-ease)] motion-safe:group-hover/model:scale-110",
            )}
          />
          <span
            className={vx(
              RING,
              "size-28 border-white/[0.08] transition-transform delay-75 duration-700 ease-[var(--vs-ease)] motion-safe:group-hover/model:scale-110",
            )}
          />
          <span className={vx(RING, "size-48 border-white/[0.05]")} />
        </span>
        {/* Буква вендора уходит под нижний край шапки: срез читается как задуманный, а не как случайный. */}
        <span
          aria-hidden
          className="absolute -bottom-7 right-2 select-none text-[84px] font-bold leading-none tracking-tighter text-white/[0.06]"
        >
          {vendorInitialByOpenRouterId(model.id)}
        </span>
        <span className={vx(VS_ON_MEDIA, "absolute left-2.5 top-2.5")}>{vendorLabelByOpenRouterId(model.id)}</span>
        {model.locked && (
          <span
            aria-hidden
            className="absolute right-2.5 top-2.5 grid size-6 place-items-center rounded-full bg-black/65 text-white"
          >
            <FiLock className="size-3" />
          </span>
        )}
        {eta && (
          <span className="absolute bottom-2.5 left-3 inline-flex items-center gap-1 text-[11px] font-medium leading-none text-white/65">
            <FiClock className="size-3" aria-hidden />
            {tx(t, "settings.eta", { t: txRef(t, eta) })}
          </span>
        )}
      </span>

      <span className="flex w-full flex-1 flex-col gap-2.5 p-3.5">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className="min-w-0 max-w-full truncate text-[15px] font-semibold leading-tight text-foreground">
            {model.name}
          </span>
          {model.badge && (
            <span className={vx(VS_TAG_GOLD, "min-w-0 max-w-full")}>
              <span className="truncate">{model.badge}</span>
            </span>
          )}
        </span>

        {facts.length > 0 && (
          <span className="flex flex-wrap gap-1">
            {facts.map((fact) => (
              <span key={fact.kind === "badge" ? fact.ref.key : fact.kind} className={VS_TAG}>
                {fact.kind === "badge"
                  ? txRef(t, fact.ref)
                  : t("home.models.aspects", { defaultValue: "Пропорций: {{n}}", n: fact.n })}
              </span>
            ))}
          </span>
        )}

        <span className="mt-auto flex items-center justify-between gap-2 pt-0.5">
          <span className="min-w-0 truncate text-[13px] font-semibold tabular-nums text-foreground">
            {price ? txRef(t, price) : ""}
          </span>
          {selected ? (
            <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-accent">
              <FiCheck className="size-3.5" aria-hidden />
              {t("home.models.selected", { defaultValue: "Выбрано" })}
              {model.locked && <span className="sr-only">{tx(t, "settings.locked")}</span>}
            </span>
          ) : model.locked ? (
            // Подпись в одно слово: она не сжимается, и длинная выдавливала из
            // строки цену — в узкой карточке от суммы оставалось «1…». Замок
            // рядом договаривает остальное, скринридеру — полная фраза.
            <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-muted">
              <FiLock className="size-3" aria-hidden />
              <span aria-hidden>{t("home.models.locked", { defaultValue: "Платный" })}</span>
              <span className="sr-only">{tx(t, "settings.locked")}</span>
            </span>
          ) : (
            <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-muted transition-colors group-hover/model:text-foreground">
              {t("home.models.select", { defaultValue: "Выбрать" })}
              <FiArrowRight
                className="size-3.5 transition-transform duration-300 motion-safe:group-hover/model:translate-x-0.5"
                aria-hidden
              />
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

// Лента перерисовывается на каждую букву в запросе (она читает стор) — карточкам это ни к чему.
export default memo(ModelCard);
