"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface ChangingTextProps {
	textList?: any;
	delay?: number
}

function DefaultTextList() {
	const { i18n } = useTranslation();
	const { t } = useTranslation('common');
	const language = i18n.language;
	const list: any = {
		ru: ["Текст", "Песни", "Голоса", "Музыка", "Обложки"],
		en: ["Text", "Songs", "Voices", "Music", "Covers"],
		kg: ["Текст", "Ырлар", "Үндөр", "Музыка", "Капкактар"],
	};

	return list[language] || list.kg;
}

export function TextChanging({
	textList = DefaultTextList(),
	delay = 3000,
}: ChangingTextProps) {
	const [currentIndex, setCurrentIndex] = useState(0);

	useEffect(() => {
		const interval = setInterval(() => {
			setCurrentIndex((prev) => (prev + 1) % textList.length);
		}, delay);

		return () => clearInterval(interval);
	}, []);

	return (
		<p className="text-5xl font-bold text-center text-rose-500 transition-all duration-500">
			{textList[currentIndex]}
		</p>
	);
}

export function TextTag({ text = "Текст", className = "" }: { text?: string; className?: string }) {
	return (
		<div className="px-6 py-3 rounded-xl bg-indigo-600/20 w-fit">
			<span className={`text-sm font-bold ${className}`}>{text}</span>
		</div>
	);
}

export function TextChangingTag({
	textList = DefaultTextList(),
	className = "",
	delay = 3000,
}: {
	textList?: any;
	delay?: number;
	className?: string;
}) {
	const [currentIndex, setCurrentIndex] = useState(0);
	const [fade, setFade] = useState(true);
	

	useEffect(() => {
		const interval = setInterval(() => {
			setFade(false);
			setTimeout(() => {
				setCurrentIndex((prev) => (prev + 1) % textList.length);
				setFade(true);
			}, 500);
		}, delay);

		return () => clearInterval(interval);
	}, [textList.length, delay]);

	return (
		<div className="px-7 py-3 rounded-xl bg-indigo-600/20 w-fit overflow-hidden flex items-center justify-center">
			<span
				className={`text-sm font-bold transition-all duration-500 transform
					${fade ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-3"}
					${className}`}
			>
				{textList[currentIndex]}
			</span>
		</div>
	);
}
