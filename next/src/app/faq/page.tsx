"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Questions from "@/components/global/Questions";

// Линкуем e-mail (support@esai.kg) и Telegram-хэндлы (@EsAI_support) в тексте ответа.
const LINK_RE = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})|@([A-Za-z0-9_]{3,})/g;

function linkify(text: string): ReactNode[] {
	const nodes: ReactNode[] = [];
	let last = 0;
	let key = 0;
	let m: RegExpExecArray | null;
	LINK_RE.lastIndex = 0;
	while ((m = LINK_RE.exec(text)) !== null) {
		if (m.index > last) nodes.push(text.slice(last, m.index));
		if (m[1]) {
			nodes.push(
				<a key={key++} href={`mailto:${m[1]}`} className="text-accent hover:underline">
					{m[1]}
				</a>
			);
		} else if (m[2]) {
			nodes.push(
				<a
					key={key++}
					href={`https://t.me/${m[2]}`}
					target="_blank"
					rel="noopener noreferrer"
					className="text-accent hover:underline"
				>
					@{m[2]}
				</a>
			);
		}
		last = LINK_RE.lastIndex;
	}
	if (last < text.length) nodes.push(text.slice(last));
	return nodes;
}

// Рендер ответа: массив строк → абзацы; подряд идущие строки на «•» группируем в список.
function Answer({ items }: { items: string[] }) {
	const blocks: ReactNode[] = [];
	let bullets: string[] = [];
	const flush = () => {
		if (bullets.length) {
			const cur = bullets;
			blocks.push(
				<ul key={`u${blocks.length}`} className="list-disc pl-5 space-y-1">
					{cur.map((b, i) => (
						<li key={i}>{linkify(b.replace(/^•\s*/, ""))}</li>
					))}
				</ul>
			);
			bullets = [];
		}
	};
	items.forEach((it) => {
		if (it.trim().startsWith("•")) bullets.push(it);
		else {
			flush();
			blocks.push(
				<p key={`p${blocks.length}`}>{linkify(it)}</p>
			);
		}
	});
	flush();
	return <div className="space-y-2.5">{blocks}</div>;
}

export default function FAQSection() {
	const { t } = useTranslation("common");
	const [openKey, setOpenKey] = useState<string | null>("0");

	const questions = t("faq.questions", { returnObjects: true }) as {
		[key: string]: { q: string; a: string | string[] };
	};
	const entries = questions && typeof questions === "object" ? Object.entries(questions) : [];

	return (
		<main className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
			<Breadcrumb />

			<div className="max-w-3xl mx-auto py-10 px-4">
				<h2 className="text-3xl font-semibold mb-8 text-center pb-6">{t("faq.title")}</h2>

				{/* Аккордеон: один открытый вопрос за раз */}
				<div className="space-y-3">
					{entries.map(([key, item]) => {
						const isOpen = openKey === key;
						const items = Array.isArray(item.a) ? item.a : [item.a];
						return (
							<div
								key={key}
								className="rounded-xl border border-border bg-surface-2 overflow-hidden transition-colors"
							>
								<button
									type="button"
									onClick={() => setOpenKey(isOpen ? null : key)}
									aria-expanded={isOpen}
									className="w-full flex items-center justify-between gap-4 px-5 py-4 text-left cursor-pointer hover:bg-surface transition-colors"
								>
									<span className="font-medium text-foreground">{item.q}</span>
									<FiChevronDown
										className={`shrink-0 text-muted transition-transform duration-200 ${
											isOpen ? "rotate-180 text-accent" : ""
										}`}
									/>
								</button>
								<div
									className="grid transition-all duration-200"
									style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
								>
									<div className="overflow-hidden">
										<div className="px-5 pb-4 text-sm text-muted leading-relaxed">
											<Answer items={items} />
										</div>
									</div>
								</div>
							</div>
						);
					})}
				</div>

				{/* Обращение команды EsAI */}
				<div className="mt-10 rounded-2xl border border-accent/30 bg-accent/5 p-6 md:p-8 text-center">
					<p className="text-lg font-semibold text-foreground">
						{t("faq.team.title", {
							defaultValue: "💛 Наша цель — сделать лучшие мировые нейросети доступными каждому.",
						})}
					</p>
					<p className="text-muted mt-2 max-w-2xl mx-auto">
						{t("faq.team.text", {
							defaultValue:
								"Если у вас есть идеи, замечания или предложения по улучшению EsAI — мы всегда рады вашей обратной связи.",
						})}
					</p>
				</div>
			</div>

			<Questions />
		</main>
	);
}
