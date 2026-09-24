/**
 * Видеостудия: вид чипа «@Image N» — классы по состоянию (§9.6).
 *
 * Отдельный модуль без TipTap: классы нужны и чипу в редакторе (vsRef.ts,
 * грузится лениво), и списку «@» и запасной textarea, и чипу вне редактора
 * (RefChip.tsx) — а они живут в основном куске страницы.
 */
import type { RefChipState } from "@/lib/vstudio/types";

const CHIP_BASE =
  "vs-chip inline-flex items-center max-w-full align-baseline mx-px px-1.5 rounded-md border text-[0.92em] " +
  "font-medium leading-[1.45] whitespace-nowrap select-none cursor-default transition-colors";

/** Классы по состоянию: акцент — только у готового чипа (§9.2), выключенный — серый, беда — красный. */
export const CHIP_STATE_CLASS: Record<RefChipState, string> = {
  ok: "bg-accent-soft text-accent border-accent/40",
  pending: "bg-surface-3 text-muted border-border animate-pulse",
  failed: "bg-status-fail/10 text-status-fail border-status-fail/50",
  deleted: "bg-status-fail/10 text-status-fail border-status-fail/50 line-through decoration-1",
  excluded: "bg-surface-2 text-muted-2 border-dashed border-border",
  missing: "bg-status-fail/10 text-status-fail border-dashed border-status-fail/60",
};
const CHIP_SELECTED = "ring-2 ring-accent ring-offset-1 ring-offset-surface";

export function chipClassName(state: RefChipState, selected = false): string {
  return `${CHIP_BASE} ${CHIP_STATE_CLASS[state] || CHIP_STATE_CLASS.missing}${selected ? ` ${CHIP_SELECTED}` : ""}`;
}
