"use client";

import "@/assets/style.scss";
import Chat from "@/components/Chat/Chat";
import DashboardNav from "@/components/Nav/DashboardNav";
import { VscBell } from "react-icons/vsc";
import "./dashboard.scss";
import { Button } from "@/components/UI/Buttons/Buttons";
import { useState } from "react";

type LocaleOption = {
	label: string;
	value: string;
	icon: string;
};

type CurrencyOption = {
	label: string;
	value: string;
};

type StaticOption = {
	label: string;
	href: string
}

const localOptions: LocaleOption[] = [
	{ label: "Русский", value: "ru", icon: "/images/local/ru.webp" },
	{ label: "English", value: "en", icon: "/images/local/en.webp" },
	{ label: "Кыргызча", value: "kg", icon: "/images/local/kg.webp" },
];

const currencyOptions: CurrencyOption[] = [
	{ label: "KGS", value: "kgs" },
	{ label: "USD", value: "usd" },
	{ label: "EUR", value: "eur" },
];




export function DropdownLocal() {
	const [open, setOpen] = useState(false);
	const [selected, setSelected] = useState<LocaleOption>(localOptions[0]);

	const handleSelect = (item: LocaleOption) => {
		setSelected(item);
		setOpen(false);
	};

	return (
		<div className="relative inline-block text-left">
			<button
				onClick={() => setOpen((prev) => !prev)}
				className="text-white rounded-md hover:text-indigo-500 bg-neutral-800 py-2 px-3 cursor-pointer transition flex items-center gap-2"
			>
				<img src={selected.icon} alt={selected.label} className="w-5 h-5 rounded-full" />
				{selected.label}
			</button>

			<div
				className={`absolute left-0 mt-2 w-48 rounded-md shadow-lg bg-neutral-900 transform transition-all duration-300 origin-top z-10 ${
					open ? "scale-100 opacity-100" : "scale-95 opacity-0 pointer-events-none"
				}`}
			>
				<ul className="py-2">
					{localOptions.map((item) => (
						<li
							key={item.value}
							onClick={() => handleSelect(item)}
							className="px-4 py-2 hover:bg-indigo-600 duration-300 cursor-pointer text-white flex items-center gap-2"
						>
							<img src={item.icon} alt={item.label} className="w-5 h-5 rounded-full" />
							{item.label}
						</li>
					))}
				</ul>
			</div>
		</div>
	);
}

export function DropdownCurrency() {
	const [open, setOpen] = useState(false);
	const [selected, setSelected] = useState<CurrencyOption>(currencyOptions[0]);

	const handleSelect = (item: CurrencyOption) => {
		setSelected(item);
		setOpen(false);
	};

	return (
		<div className="relative inline-block text-left">
			<button
				onClick={() => setOpen((prev) => !prev)}
				className="text-white rounded-md hover:text-indigo-500 bg-neutral-800 py-2 px-3 cursor-pointer transition flex items-center gap-2"
			>
				{selected.label}
			</button>

			<div
				className={`absolute left-0 mt-2 w-40 rounded-md shadow-lg bg-neutral-900 transform transition-all duration-300 origin-top z-10 ${
					open ? "scale-100 opacity-100" : "scale-95 opacity-0 pointer-events-none"
				}`}
			>
				<ul className="py-2">
					{currencyOptions.map((item) => (
						<li
							key={item.value}
							onClick={() => handleSelect(item)}
							className="px-4 py-2 hover:bg-indigo-600 duration-300 cursor-pointer text-white"
						>
							{item.label}
						</li>
					))}
				</ul>
			</div>
		</div>
	);
}

export function StaticDropdown() {
	const [open, setOpen] = useState(false);

	const handleSelect = (item: string) => {
		setOpen(false);
	};

	const items = ["Уведомление 1", "Уведомление 2", "Уведомление 3"];

	return (
		<div className="relative inline-block text-left">
			<Button
				onClick={() => setOpen((prev) => !prev)}
				className=" text-white p-1 rounded-md hover:text-indigo-700 transition"
			>
				<i>
					<VscBell className="chat-button-icon" />
				</i>
			</Button>

			<div
				className={`absolute left-0 mt-2 w-48 rounded-md shadow-lg bg-neutral-900 transform transition-all duration-300 origin-top z-10 ${
					open ? "scale-100 opacity-100" : "scale-95 opacity-0 pointer-events-none"
				}`}
			>
				<ul className="py-2">
					{items.map((item) => (
						<li
							key={item}
							onClick={() => handleSelect(item)}
							className="px-4 py-2 hover:bg-indigo-600 duration-300 cursor-pointer text-white"
						>
							{item}
						</li>
					))}
				</ul>
			</div>
		</div>
	);
}


export default function Dashboard() {
	return (
		<main className="antialiased mx-auto h-full flex bg-neutral-800/75">
			<div className="w-3/12">
				<DashboardNav />
			</div>
			<div className="flex flex-grow">
				<Chat />
			</div>
			<div className="w-3/12 flex items-start">
				<div className="flex items-center w-full justify-end gap-3 p-4">
					<StaticDropdown />
					<DropdownLocal />
					<DropdownCurrency />
				</div>
			</div>
		</main>
	);
}
