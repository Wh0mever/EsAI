/**
 * Видеостудия, редактор промпта: чип-ссылка на материал (узел vsRef, §9.5).
 *
 * Сам узел, NodeView и хранилище меток — в vsRef.ts (без JSX: их гоняют
 * node-тесты на настоящей схеме). Модуль тянет TipTap, поэтому импортирует
 * его только TipTapEditor (ленивый кусок). Чип вне редактора — RefChip.tsx,
 * классы чипа — chipStyle.ts: они без TipTap.
 */
export { RefStore, VsRef, type VsRefOptions } from "./vsRef";
export { CHIP_STATE_CLASS, chipClassName } from "./chipStyle";
