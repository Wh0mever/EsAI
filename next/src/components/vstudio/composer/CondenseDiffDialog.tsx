"use client";

/**
 * Видеостудия, композер: «Сжать с ИИ» — было / стало (§4.8).
 *
 * Ничего не меняется без согласия человека: он видит исходный и сжатый текст
 * рядом (на телефоне — друг под другом), с чипами фото на своих местах и
 * числом символов и слов, и выбирает «Принять» или «Оставить как есть».
 */
import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import { missingLabel } from "@/lib/vstudio/labels";
import type { PromptDoc, RefLabels, TextStats } from "@/lib/vstudio/types";
import { RefChip } from "../editor/RefChip";
import { VS_BTN_GHOST, VS_BTN_GOLD, VS_LABEL, vx } from "../ui/skin";
import { fmtNum } from "./composerLogic";
import { ct } from "./composerText";

export type CondenseResult = { before: PromptDoc; after: PromptDoc; statsBefore: TextStats; statsAfter: TextStats };

export type CondenseDiffDialogProps = {
  open: boolean;
  result: CondenseResult | null;
  labels: RefLabels;
  onAccept: () => void;
  onKeep: () => void;
};

function DocView({ doc, labels }: { doc: PromptDoc; labels: RefLabels }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div className="flex flex-col gap-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
      {(doc.blocks || []).map((block, bi) => (
        <p key={bi} className="min-h-[1em]">
          {block.map((node, ni) =>
            node.t === "text" ? (
              <Fragment key={ni}>{node.v}</Fragment>
            ) : (
              <RefChip key={ni} label={labels[node.asset] ?? missingLabel(t)} />
            ),
          )}
        </p>
      ))}
    </div>
  );
}

function Column({ title, stats, doc, labels, accent }: { title: string; stats: TextStats; doc: PromptDoc; labels: RefLabels; accent?: boolean }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <section className={vx("vs-card flex min-w-0 flex-1 flex-col gap-2 rounded-2xl p-3.5", accent && "vs-card-on")}>
      <header className="flex items-baseline justify-between gap-2">
        <h3 className={vx(VS_LABEL, accent && "!text-vs-accent")}>{title}</h3>
        <span className="text-xs tabular-nums text-muted">
          {ct(t, "assist.stats", { chars: fmtNum(stats.chars), words: fmtNum(stats.words) })}
        </span>
      </header>
      <div className="max-h-[40vh] overflow-y-auto overscroll-contain pr-1 md:max-h-[50vh]">
        <DocView doc={doc} labels={labels} />
      </div>
    </section>
  );
}

export default function CondenseDiffDialog({ open, result, labels, onAccept, onKeep }: CondenseDiffDialogProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  if (!result) return null;
  return (
    <Modal title={ct(t, "assist.title")} open={open} onClose={onKeep} size="lg" mobileFull>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row">
          <Column title={ct(t, "assist.before")} stats={result.statsBefore} doc={result.before} labels={labels} />
          <Column title={ct(t, "assist.after")} stats={result.statsAfter} doc={result.after} labels={labels} accent />
        </div>
        <p className="text-xs text-muted">{ct(t, "assist.note")}</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onKeep}
            className={VS_BTN_GHOST}
          >
            {ct(t, "assist.keep")}
          </button>
          <button
            type="button"
            onClick={onAccept}
            className={VS_BTN_GOLD}
          >
            {ct(t, "assist.accept")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
