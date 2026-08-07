'use client';

import "./DropDown.scss";
import { FaAngleDown } from "react-icons/fa6";

type DropDownHoveredProps = {
    children: React.ReactNode;
    handleText: React.ReactNode
  };

export function DropDownHovered({ children, handleText }: DropDownHoveredProps) {
	return (
        <div className="drop-down-hovered">
            <a href="#" onClick={(e) => {e.preventDefault()}} className="flex items-center gap-3 drop-down-link">
                {handleText} <FaAngleDown />
            </a>
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
