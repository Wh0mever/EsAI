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
  ok: "bg-accent/[0.12] text-accent border-accent/40",
  pending: "bg-white/[0.07] text-muted border-white/10 animate-pulse motion-reduce:animate-none",
  failed: "bg-status-fail/10 text-status-fail border-status-fail/50",
  deleted: "bg-status-fail/10 text-status-fail border-status-fail/50 line-through decoration-1",
  excluded: "bg-white/[0.04] text-muted-2 border-dashed border-white/15",
  missing: "bg-status-fail/10 text-status-fail border-dashed border-status-fail/60",
};
// Без зазора вокруг кольца: поле запроса прозрачное, и зазор цвета подложки был бы виден пятном.
const CHIP_SELECTED = "ring-2 ring-accent/80";

export function chipClassName(state: RefChipState, selected = false): string {
  return `${CHIP_BASE} ${CHIP_STATE_CLASS[state] || CHIP_STATE_CLASS.missing}${selected ? ` ${CHIP_SELECTED}` : ""}`;
}
