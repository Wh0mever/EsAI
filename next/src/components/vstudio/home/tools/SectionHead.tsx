import type { ReactNode } from "react";
import { VS_H2, VS_SUB, vx } from "../../ui/skin";

type SectionHeadProps = {
  /** id заголовка: секция ссылается на него через aria-labelledby. */
  id: string;
  title: string;
  sub?: string;
  /** Действие справа: переключатель, ссылка. На узком экране уходит под заголовок. */
  children?: ReactNode;
};

/** Шапка секции первого экрана: заголовок с пояснением слева, действие справа (§2.2). */
export default function SectionHead({ id, title, sub, children }: SectionHeadProps) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        <h2 id={id} className={VS_H2}>
          {title}
        </h2>
        {sub && <p className={vx(VS_SUB, "mt-2 max-w-xl")}>{sub}</p>}
      </div>
      {children}
    </div>
  );
}
