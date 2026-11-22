'use client';

import "./DropDown.scss";
import { useState } from "react";
import { FaAngleDown } from "react-icons/fa6";

type DropDownHoveredProps = {
    children: React.ReactNode;
    handleText: React.ReactNode
  };

// Мышь: открывается при наведении (как раньше). Клавиатура: Enter/Space на кнопке
// открывает и закрывает, Escape закрывает и возвращает фокус на кнопку, уход
// фокуса из меню закрывает. Закрытая панель скрыта visibility — ссылки внутри
// не попадают в обход Tab невидимыми (WCAG 2.4.7, 4.1.2).
export function DropDownHovered({ children, handleText }: DropDownHoveredProps) {
    const [open, setOpen] = useState(false);
	return (
        <div
            className={`drop-down-hovered${open ? " is-open" : ""}`}
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => setOpen(false)}
            onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
            }}
            onKeyDown={(e) => {
                if (e.key !== "Escape" || !open) return;
                setOpen(false);
                e.currentTarget.querySelector<HTMLElement>(".drop-down-link")?.focus();
            }}
        >
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex items-center gap-3 drop-down-link cursor-pointer"
                aria-haspopup="true"
                aria-expanded={open}
            >
                {handleText} <FaAngleDown aria-hidden="true" />
            </button>
            <div className="drop-down-menu py-5">
                {/* Панель следует теме: на светлой странице тёмное выпадающее меню
                    выглядело чужеродно. Рамка нужна, чтобы в светлой теме панель
                    отделялась от фона страницы. */}
                <div className="flex column rounded-lg bg-surface border border-border text-foreground shadow-lg drop-down-menu-wrapper">
                    {children}
                </div>
            </div>
        </div>
	);
}
