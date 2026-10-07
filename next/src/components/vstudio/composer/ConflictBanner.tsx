"use client";

/**
 * Видеостудия, композер: кадры и фото-референсы одновременно (§0 п. 9, §4.4).
 *
 * Для API это разные режимы: frame_images побеждает input_references, и
 * вместе они не уходят никогда. Если модель не умеет «первый кадр как Image k»
 * (frames_with_refs = block/none), компилятор отдаёт frames_refs_conflict, а
 * здесь — объяснение словами и выбор одной кнопкой: «Оставить кадры» или
 * «Оставить референсы». Второе не удаляется — становится серым и не
 * оплачивается. last_frame_with_refs — та же беда с последним кадром.
 */
import { useTranslation } from "react-i18next";
import { FiShuffle } from "react-icons/fi";
import { issueText } from "@/lib/vstudio/errors";
import type { CompilerIssue, IssueFix } from "@/lib/vstudio/types";
import { vx } from "../ui/skin";
import { conflictFixes } from "./composerLogic";
import { fixLabel } from "./ComposerHints";
import { ct } from "./composerText";
import { HINT_BTN, HINT_BTN_PRIMARY, HINT_BTN_QUIET } from "./dockSkin";

export type ConflictBannerProps = {
  issue: CompilerIssue;
  onFix: (fix: IssueFix) => void;
};

export default function ConflictBanner({ issue, onFix }: ConflictBannerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const last = issue.code === "last_frame_with_refs";
  const fixes = conflictFixes(issue);
  return (
    <div
      role="alert"
      className="vs-card flex shrink-0 flex-col gap-2 rounded-2xl !border-status-wait/45 px-3.5 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-3"
    >
      <FiShuffle className="hidden size-4 shrink-0 text-status-wait sm:block" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-foreground">{ct(t, last ? "conflict.lastTitle" : "conflict.title")}</div>
        <div className="text-xs leading-snug text-muted">{issueText(t, issue, "errors")}</div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {fixes.map((fix, i) => (
          <button
            key={`${fix.action}:${i}`}
            type="button"
            onClick={() => onFix(fix)}
            className={vx(HINT_BTN, i === 0 ? HINT_BTN_PRIMARY : HINT_BTN_QUIET)}
          >
            {fix.action === "use_frames_only"
              ? ct(t, "conflict.useFrames")
              : fix.action === "use_refs_only"
                ? ct(t, "conflict.useRefs")
                : fix.action === "exclude_inputs" && last
                  ? ct(t, "conflict.dropLast")
                  : fixLabel(t, fix)}
          </button>
        ))}
      </div>
    </div>
  );
}
