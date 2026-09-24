/**
 * Видеостудия: чип «@Image N» вне редактора — карточка кадра в ленте,
 * «Что ушло модели», подсказки композера. Тот же вид, что у чипа в тексте
 * (chipStyle.ts), но без TipTap: импорт отсюда не тянет редактор в кусок страницы.
 */
import type { RefLabel } from "@/lib/vstudio/types";
import { chipClassName } from "./chipStyle";

export function RefChip({ label, className = "" }: { label: RefLabel; className?: string }) {
  return (
    <span role="img" aria-label={label.aria} title={label.aria} className={`${chipClassName(label.state)} ${className}`}>
      {label.text}
    </span>
  );
}

export default RefChip;
