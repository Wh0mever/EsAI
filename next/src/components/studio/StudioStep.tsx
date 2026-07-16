"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { FiArrowRight, FiCheck, FiLock } from "react-icons/fi";
import type { CartoonModel } from "./StudioClient";

type Props = {
	id: string;
	number: number;
	emoji: string;
	icon: React.ReactNode;
	title: string;
	subtitle: string;
	/** «что получится» — простыми словами. */
	result: string;
	models: CartoonModel[];
	loading: boolean;
	/** примеры-подсказки; первый становится текстом q= для deep-link. */
	examples: string[];
	cta: string;
	delay?: number;
};

/** Ключ модели для deep-link — openrouter_id (как ожидает ChatWorkspace). */
const modelKey = (m: CartoonModel) => String(m.openrouter_id || m.id);

/**
 * StudioStep — крупная пронумерованная карточка одного этапа конвейера.
 * Показывает доступные модели маленькими чипами (человек выбирает одну),
 * примеры-подсказки и кнопку, которая ведёт в чат с выбранной моделью и
 * подставленным примером через deep-link `/?model=<id>&q=<prompt>`.
 */
export default function StudioStep({
	id,
	number,
	emoji,
	icon,
	title,
	subtitle,
	result,
	models,
	loading,
	examples,
	cta,
	delay = 0,
}: Props) {
	const { t } = useTranslation("common");
	// Выбранная модель для этого шага (первая доступная по умолчанию).
	const [selected, setSelected] = useState<string>("");
	// Выбранный пример-подсказка (подставится в q=).
	const [prompt, setPrompt] = useState<string>(examples[0] || "");

	useEffect(() => {
		if (models.length === 0) return;
		const firstFree = models.find((m) => !m.locked) || models[0];
		setSelected((prev) => prev || modelKey(firstFree));
	}, [models]);

	// Ссылка «в чат»: главная «/» = рабочий чат, поддерживает ?model=&q=.
	const href = `/?model=${encodeURIComponent(selected)}${
		prompt ? `&q=${encodeURIComponent(prompt)}` : ""
	}`;

	const canGo = Boolean(selected);

	return (
		<motion.div
			id={id}
			initial={{ opacity: 0, y: 20 }}
			whileInView={{ opacity: 1, y: 0 }}
			viewport={{ once: true, margin: "-60px" }}
			transition={{ duration: 0.5, delay }}
			className="relative flex flex-col rounded-3xl border border-border bg-surface p-6 shadow-sm transition-shadow hover:shadow-xl hover:border-accent/40 scroll-mt-24"
		>
			{/* Крупный номер + иконка */}
			<div className="flex items-center gap-4">
				<span className="relative grid h-16 w-16 shrink-0 place-items-center rounded-2xl bg-accent-soft text-3xl">
					{emoji}
					<span className="absolute -right-2 -top-2 grid h-7 w-7 place-items-center rounded-full bg-accent text-sm font-bold text-on-accent shadow">
						{number}
					</span>
				</span>
				<div className="min-w-0">
					<h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
						<span className="text-accent">{icon}</span>
						{title}
					</h3>
				</div>
			</div>

			<p className="mt-4 text-[15px] text-foreground leading-relaxed">{subtitle}</p>

			{/* Что получится */}
			<div className="mt-3 inline-flex items-start gap-2 rounded-xl bg-surface-2 px-3 py-2 text-sm text-muted">
				<FiCheck className="mt-0.5 shrink-0 text-accent" />
				<span>{result}</span>
			</div>

			{/* Чипы моделей — простая подпись «Чем сделать» без жаргона */}
			<div className="mt-5">
				<div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-2">
					{t("studio.step.choose", { defaultValue: "Чем сделать" })}
				</div>
				{loading ? (
					<div className="flex flex-wrap gap-2">
						{[0, 1, 2].map((i) => (
							<span
								key={i}
								className="h-7 w-24 animate-pulse rounded-full bg-surface-2"
							/>
						))}
					</div>
				) : models.length === 0 ? (
					<p className="text-sm text-muted-2 italic">
						{t("studio.step.no_models", { defaultValue: "Скоро добавим варианты" })}
					</p>
				) : (
					<div className="flex flex-wrap gap-2">
						{models.map((m) => {
							const key = modelKey(m);
							const active = key === selected;
							const locked = !!m.locked;
							return (
								<button
									key={key}
									type="button"
									onClick={() => setSelected(key)}
									title={locked ? `${m.name} — ${t("studio.step.locked", { defaultValue: "Доступно в платном пакете" })}` : m.name}
									className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors cursor-pointer ${
										active
											? "border-accent bg-accent-soft text-foreground"
											: "border-border bg-surface-2 text-muted hover:border-accent/50 hover:text-foreground"
									}`}
								>
									{active && <FiCheck className="text-accent" />}
									<span className="max-w-[11rem] sm:max-w-[9rem] truncate">{m.name}</span>
									{locked && <FiLock className="text-[12px] text-muted-2" />}
								</button>
							);
						})}
					</div>
				)}
			</div>

			{/* Примеры-подсказки — клик выбирает текст, который уедет в чат */}
			{examples.length > 0 && (
				<div className="mt-5">
					<div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-2">
						{t("studio.step.examples", { defaultValue: "Например, попробуйте" })}
					</div>
					<div className="flex flex-col gap-2">
						{examples.map((ex) => {
							const active = ex === prompt;
							return (
								<button
									key={ex}
									type="button"
									onClick={() => setPrompt(ex)}
									className={`text-left rounded-xl border px-3 py-2 text-sm leading-snug transition-colors cursor-pointer ${
										active
											? "border-accent/60 bg-accent-soft text-foreground"
											: "border-border bg-surface-2/60 text-muted hover:border-accent/40 hover:text-foreground"
									}`}
								>
									«{ex}»
								</button>
							);
						})}
					</div>
				</div>
			)}

			{/* Кнопка → чат с выбранной моделью и подставленным примером */}
			<div className="mt-auto pt-6">
				<a
					href={canGo ? href : undefined}
					aria-disabled={!canGo}
					className={`group flex w-full items-center justify-center gap-2 rounded-2xl px-5 py-3.5 text-base font-bold transition-colors ${
						canGo
							? "bg-accent text-on-accent hover:bg-accent-strong"
							: "cursor-not-allowed bg-surface-2 text-muted-2"
					}`}
				>
					{cta}
					<FiArrowRight className="transition-transform group-hover:translate-x-0.5" />
				</a>
			</div>
		</motion.div>
	);
}
