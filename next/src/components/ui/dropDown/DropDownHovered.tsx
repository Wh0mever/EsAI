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
                <div className="flex column rounded-lg bg-neutral-900 drop-down-menu-wrapper">
                    {children}
                </div>
            </div>
        </div>
	);
}
