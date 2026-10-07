"use client";

/**
 * «Как модель использует ваши фото»: одной фразой — режим (только текст,
 * первый кадр, референсы, кадр как Image k…), ниже — строка на каждый
 * материал: «@Image 1 — героиня», «@Первый кадр — видео начнётся с него»,
 * серое «не учитывается и не оплачивается».
 *
 * Режим считается тем же правилом, что в компиляторе (settingsModel.localMode),
 * чтобы объяснение появлялось сразу; если есть свежий quote — берём его mode
 * и метки: модель получит ровно то, что написано здесь.
 */
import { useTranslation } from "react-i18next";
import { FiImage, FiInfo } from "react-icons/fi";
import { SUBJECT_RU } from "@/lib/vstudio/errors";
import type { ComposerFrames, ModelJSON, QuoteJSON, TrayItem, VsKind } from "@/lib/vstudio/types";
import { VS_FOCUS } from "../ui/skin";
import { Pill, Reason, Section, cx } from "./SettingsBits";
import { countInputs, explainRows, localMode, modeText, modelFacts, type ExplainRow, type LocalMode } from "./settingsModel";
import { tx, txRef, type Translate } from "./settingsText";

export type InputsExplainerProps = {
  kind: VsKind;
  model: ModelJSON | null;
  tray: TrayItem[];
  frames: ComposerFrames;
  /** Только свежий quote (его key совпал с текущим телом); иначе null. */
  quote?: QuoteJSON | null;
  /** «Выбрать другую модель», когда эта не умеет с фото. */
  onPickModel?: () => void;
};

function rowLabel(t: Translate, row: ExplainRow): string {
  if (row.slot === "reference") return row.label;
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(`subject.${row.slot}`, { ns: "vstudio", defaultValue: SUBJECT_RU[row.slot] });
  return typeof out === "string" ? out : SUBJECT_RU[row.slot];
}

export default function InputsExplainer({ kind, model, tray, frames, quote, onPickModel }: InputsExplainerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const counts = countInputs(tray, frames);
  const local = localMode(kind, model, counts);
  const lm: LocalMode = quote?.mode ? { ...local, mode: quote.mode } : local;
  const rows = explainRows(kind, model, tray, frames, { mode: lm.mode, pinK: lm.pinK, labels: quote?.labels });
  const facts = model ? modelFacts(model, kind) : [];
  const text = modeText(kind, model, lm, counts);
  const trouble = lm.issue !== null;
  // Совет про роль — один раз под списком, а не в каждой строке.
  const needsRole = rows.some((r) => r.note?.key === "settings.refNoRole");

  return (
    <Section title={tx(t, "settings.howRefsUsed")} icon={<FiImage />}>
      <div
        className={cx(
          "flex gap-2 rounded-xl px-3 py-2.5 text-xs leading-relaxed",
          trouble ? "border border-status-wait/40 bg-status-wait/[0.06] text-foreground" : "vs-card text-muted",
        )}
        aria-live="polite"
      >
        <FiInfo className={cx("mt-0.5 size-3.5 shrink-0", trouble ? "text-status-wait" : "text-muted-2")} aria-hidden />
        <div className="flex min-w-0 flex-col gap-1.5">
          <span>{txRef(t, text)}</span>
          {trouble && lm.issue === "refsOff" && onPickModel && (
            <button
              type="button"
              onClick={onPickModel}
              // Отрицательные поля: на телефоне зона нажатия 44 px, а строка остаётся высотой 32 px.
              className={cx(
                "-my-1.5 inline-flex min-h-11 cursor-pointer items-center self-start rounded-md text-xs font-semibold text-foreground underline underline-offset-2 transition-colors hover:text-accent md:my-0 md:min-h-8",
                VS_FOCUS,
              )}
            >
              {tx(t, "settings.pickOther")}
            </button>
          )}
        </div>
      </div>

      {rows.length > 0 && (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li key={row.lid} className={cx("flex items-center gap-2", row.tone === "muted" && "opacity-70")}>
              <span className="relative size-9 shrink-0 overflow-hidden rounded-lg border border-white/10 bg-white/[0.05]">
                {row.preview && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={row.preview} alt="" className={cx("size-full object-cover", row.tone === "muted" && "grayscale")} />
                )}
              </span>
              <div className="min-w-0 flex-1 break-words text-xs leading-snug">
                <span className={cx("font-semibold", row.label === "—" ? "text-muted-2" : "text-foreground")}>
                  {row.role ? tx(t, "settings.refRole", { label: rowLabel(t, row), role: row.role }) : rowLabel(t, row)}
                </span>
                {row.note && (
                  <span
                    className={cx(
                      "block",
                      row.tone === "error" && "text-status-fail",
                      row.tone === "warn" && "text-status-wait",
                      (row.tone === "muted" || row.tone === "ok") && "text-muted",
                    )}
                  >
                    {txRef(t, row.note)}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {needsRole && <Reason tone="muted">{tx(t, "settings.roleHint")}</Reason>}

      {facts.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {facts.map((f) => (
            // «Без фото реальных людей» желтеет, когда в запросе уже есть свои фото.
            <Pill key={f.key} tone={f.key === "settings.fact.faces" && counts.uploads > 0 ? "warn" : "plain"}>
              {txRef(t, f)}
            </Pill>
          ))}
        </div>
      )}
    </Section>
  );
}
