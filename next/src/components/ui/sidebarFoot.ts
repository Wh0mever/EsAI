/**
 * Нижний блок бокового меню чата (ChatSidebar.tsx): развёрнут он или свёрнут.
 * Без React — проверяется sidebarFoot.test.mjs обычным Node.
 */

export const SIDEBAR_FOOT_KEY = "esai-sidebar-foot";

const FOOT_OPEN = "open";
const FOOT_CLOSED = "closed";

/** Уже этой ширины — телефон: блок съедает экран, и по умолчанию он свёрнут. */
export const SIDEBAR_FOOT_PHONE_WIDTH = 768;

/** Выбор человека важнее ширины; мусор в хранилище — как будто выбора не было. */
export function footOpenFrom(saved: string | null, width: number): boolean {
  if (saved === FOOT_OPEN) return true;
  if (saved === FOOT_CLOSED) return false;
  return width >= SIDEBAR_FOOT_PHONE_WIDTH;
}

export const footValue = (open: boolean): string => (open ? FOOT_OPEN : FOOT_CLOSED);
