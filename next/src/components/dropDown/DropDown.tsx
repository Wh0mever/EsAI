"use client";
import { useRef, useEffect } from "react";

type BaseItem = {
	label: string;
	value?: string;
	icon?: string;
};

type DropdownProps<T extends BaseItem> = {
	items: T[];
	onSelect: (item: T) => void;
	renderButton: (selected: T | null, isOpen: boolean, toggle: () => void) => React.ReactNode;
	renderItem: (item: T) => React.ReactNode;
	widthClass?: string;
	isOpen: boolean;
	close: () => void;
	selected?: T | null;
	setSelected?: (val: T) => void;
};

export default function Dropdown<T extends BaseItem>({
	items,
	onSelect,
	renderButton,
	renderItem,
	widthClass = "w-fit",
	isOpen,
	close,
	selected,
	setSelected,
}: DropdownProps<T>) {
	const containerRef = useRef<HTMLDivElement>(null);

	const handleSelect = (item: T) => {
		onSelect(item);
		setSelected?.(item);
		close();
	};

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
				close();
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => document.removeEventListener("mousedown", handleClickOutside);
	}, []);

	return (
		<div ref={containerRef} className="relative inline-block text-left">
			{renderButton(selected || null, isOpen, () => (isOpen ? close() : null))}

			<div
				className={`absolute right-0 mt-2 ${widthClass} rounded-md shadow-lg bg-surface transform transition-all duration-300 origin-top z-10 ${
					isOpen ? "scale-100 opacity-100" : "scale-95 opacity-0 pointer-events-none"
				}`}
			>
				<ul className="py-2">
					{items.map((item) => (
						<li
							key={item.value || item.label}
							onClick={() => handleSelect(item)}
							className="cursor-pointer hover:bg-surface-2 px-4 py-2 duration-300 text-foreground"
						>
							{renderItem(item)}
						</li>
					))}
				</ul>
			</div>
		</div>
	);
}