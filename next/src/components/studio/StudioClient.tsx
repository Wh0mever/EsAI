"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import {
	FiEdit3,
	FiImage,
	FiVideo,
	FiArrowRight,
	FiChevronRight,
	FiChevronDown,
	FiMic,
	FiMusic,
	FiMessageCircle,
	FiZap,
	FiSmile,
	FiPlay,
} from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import StudioStep from "./StudioStep";

/** Одна модель из ответа ai/cartoon/models/ (тот же shape, что AiModel). */
export type CartoonModel = {
	id: number | string;
	name: string;
	openrouter_id?: string;
	description?: string;
	locked?: boolean;
};

/** Ответ ai/cartoon/models/ — группы по этапу конвейера. */
type CartoonModels = {
	script: CartoonModel[];
	image: CartoonModel[];
	video: CartoonModel[];
};

const EMPTY: CartoonModels = { script: [], image: [], video: [] };

/**
 * StudioClient — визуальная студия «Создание мультфильмов». НЕ список моделей,
 * а понятный конвейер из трёх шагов. Каждый шаг ведёт в чат с подходящей
 * моделью через уже поддерживаемый deep-link `/?model=<openrouter_id>&q=<prompt>`.
 */
export default function StudioClient() {
	const { t } = useTranslation("common");
	const [models, setModels] = useState<CartoonModels>(EMPTY);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		let on = true;
		(async () => {
			try {
				// auth=true: бэк считает locked по тиру пользователя (как в ai/models/).
				const res = await fetchData<CartoonModels>("ai/cartoon/models/", "GET", null, true);
				if (!on) return;
				const d = res?.data;
				setModels({
					script: Array.isArray(d?.script) ? d!.script : [],
					image: Array.isArray(d?.image) ? d!.image : [],
					video: Array.isArray(d?.video) ? d!.video : [],
				});
			} catch {
				if (on) setModels(EMPTY);
			} finally {
				if (on) setLoading(false);
			}
		})();
		return () => {
			on = false;
		};
	}, []);

	// Примеры-подсказки для каждого шага (простой дружелюбный язык, без жаргона).
	const scriptExamples = useMemo(
		() => [
			t("studio.step1.ex1", {
				defaultValue: "Мультик про смелого котёнка, который спасает друзей",
			}),
			t("studio.step1.ex2", {
				defaultValue: "Весёлая история про робота и его собаку в космосе",
			}),
		],
		[t]
	);
	const imageExamples = useMemo(
		() => [
			t("studio.step2.ex1", { defaultValue: "Милый рыжий котёнок в синем плаще супергероя" }),
			t("studio.step2.ex2", { defaultValue: "Добрый робот с большими глазами на фоне планет" }),
		],
		[t]
	);
	const videoExamples = useMemo(
		() => [
			t("studio.step3.ex1", { defaultValue: "Котёнок бежит по цветочному полю, камера следует за ним" }),
			t("studio.step3.ex2", { defaultValue: "Робот машет рукой и улыбается, вокруг летают звёзды" }),
		],
		[t]
	);

	return (
		<main className="bg-background text-foreground">
			{/* ===================== HERO ===================== */}
			<section className="relative overflow-hidden">
				{/* Кинематографичный фон: мягкое золотое свечение + затемнение по краям. */}
				<div
					aria-hidden
					className="pointer-events-none absolute inset-0"
					style={{
						background:
							"radial-gradient(80% 60% at 50% 0%, var(--accent-soft) 0%, transparent 70%)",
					}}
				/>
				<div
					aria-hidden
					className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-72 w-[42rem] max-w-full rounded-full blur-3xl opacity-40"
					style={{ background: "var(--accent)" }}
				/>

				<div className="relative mx-auto max-w-5xl px-4 pt-16 pb-10 sm:pt-24 sm:pb-14 text-center">
					<motion.span
						initial={{ opacity: 0, y: 8 }}
						animate={{ opacity: 1, y: 0 }}
						transition={{ duration: 0.4 }}
						className="inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent-soft px-3.5 py-1.5 text-sm font-medium text-accent"
					>
						<span className="text-base">🎬</span>
						{t("studio.badge", { defaultValue: "Новый раздел EsAI" })}
					</motion.span>

					<motion.h1
						initial={{ opacity: 0, y: 12 }}
						animate={{ opacity: 1, y: 0 }}
						transition={{ duration: 0.5, delay: 0.05 }}
						className="mt-5 text-4xl sm:text-6xl font-extrabold tracking-tight text-balance"
					>
						{t("studio.hero.title", { defaultValue: "Создание мультфильмов" })}
					</motion.h1>

					<motion.p
						initial={{ opacity: 0, y: 12 }}
						animate={{ opacity: 1, y: 0 }}
						transition={{ duration: 0.5, delay: 0.12 }}
						className="mx-auto mt-4 max-w-2xl text-lg sm:text-xl text-muted text-balance"
					>
						{t("studio.hero.subtitle", {
							defaultValue:
								"Придумайте историю, нарисуйте героев и оживите их в видео — прямо здесь, без навыков.",
						})}
					</motion.p>

					{/* Мини-навигация по трём шагам — «оглавление» конвейера. */}
					<motion.div
						initial={{ opacity: 0 }}
						animate={{ opacity: 1 }}
						transition={{ duration: 0.5, delay: 0.2 }}
						className="mt-7 flex flex-wrap items-center justify-center gap-2 text-sm text-muted"
					>
						<a href="#step-1" className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 py-1.5 hover:border-accent/60 hover:text-foreground transition-colors">
							<FiEdit3 className="text-accent" /> {t("studio.step1.name", { defaultValue: "Сценарий" })}
						</a>
						<FiChevronRight className="text-muted-2 hidden sm:block" />
						<a href="#step-2" className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 py-1.5 hover:border-accent/60 hover:text-foreground transition-colors">
							<FiImage className="text-accent" /> {t("studio.step2.name", { defaultValue: "Персонажи" })}
						</a>
						<FiChevronRight className="text-muted-2 hidden sm:block" />
						<a href="#step-3" className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 py-1.5 hover:border-accent/60 hover:text-foreground transition-colors">
							<FiVideo className="text-accent" /> {t("studio.step3.name", { defaultValue: "Видео" })}
						</a>
					</motion.div>
				</div>
			</section>

			{/* ===================== КОНВЕЙЕР 3 ШАГА ===================== */}
			<section className="mx-auto max-w-6xl px-4 pb-4">
				<div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr_auto_1fr] gap-5 lg:gap-3 items-stretch">
					{/* Шаг 1 — Сценарий */}
					<StudioStep
						id="step-1"
						number={1}
						emoji="✍️"
						icon={<FiEdit3 />}
						title={t("studio.step1.title", { defaultValue: "Сценарий" })}
						subtitle={t("studio.step1.subtitle", {
							defaultValue: "Опишите идею — ИИ напишет сценарий и сцены.",
						})}
						result={t("studio.step1.result", {
							defaultValue: "Получится готовая история с героями и сценами",
						})}
						models={models.script}
						loading={loading}
						examples={scriptExamples}
						cta={t("studio.step1.cta", { defaultValue: "Начать сценарий" })}
						delay={0}
					/>

					<Connector />

					{/* Шаг 2 — Персонажи и изображения */}
					<StudioStep
						id="step-2"
						number={2}
						emoji="🎨"
						icon={<FiImage />}
						title={t("studio.step2.title", { defaultValue: "Персонажи и изображения" })}
						subtitle={t("studio.step2.subtitle", {
							defaultValue: "Опишите героя или сцену — ИИ нарисует.",
						})}
						result={t("studio.step2.result", {
							defaultValue: "Получатся красивые картинки героев и мест",
						})}
						models={models.image}
						loading={loading}
						examples={imageExamples}
						cta={t("studio.step2.cta", { defaultValue: "Нарисовать" })}
						delay={0.08}
					/>

					<Connector />

					{/* Шаг 3 — Видео и анимация */}
					<StudioStep
						id="step-3"
						number={3}
						emoji="🎬"
						icon={<FiVideo />}
						title={t("studio.step3.title", { defaultValue: "Видео и анимация" })}
						subtitle={t("studio.step3.subtitle", {
							defaultValue: "Оживите картинку или опишите сцену — получите видео.",
						})}
						result={t("studio.step3.result", {
							defaultValue: "Получится короткое видео, где всё двигается",
						})}
						models={models.video}
						loading={loading}
						examples={videoExamples}
						cta={t("studio.step3.cta", { defaultValue: "Создать видео" })}
						delay={0.16}
					/>
				</div>
			</section>

			{/* ===================== СКОРО ===================== */}
			<section className="mx-auto max-w-6xl px-4 pt-10 pb-2">
				<h2 className="text-center text-sm font-semibold uppercase tracking-wide text-muted-2">
					{t("studio.soon.title", { defaultValue: "Скоро" })}
				</h2>
				<div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl mx-auto">
					<SoonCard
						emoji="🔊"
						icon={<FiMic />}
						title={t("studio.soon.voice.title", { defaultValue: "Озвучка" })}
						subtitle={t("studio.soon.voice.subtitle", {
							defaultValue: "Голоса для героев — прочитают реплики вслух",
						})}
					/>
					<SoonCard
						emoji="🎵"
						icon={<FiMusic />}
						title={t("studio.soon.music.title", { defaultValue: "Музыка" })}
						subtitle={t("studio.soon.music.subtitle", {
							defaultValue: "Своя мелодия и звуки для мультфильма",
						})}
					/>
				</div>
			</section>

			{/* ===================== КАК ЭТО РАБОТАЕТ ===================== */}
			<section className="mx-auto max-w-5xl px-4 pt-14 pb-20">
				<h2 className="text-center text-2xl sm:text-3xl font-bold text-balance">
					{t("studio.how.title", { defaultValue: "Как это работает" })}
				</h2>
				<div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-5">
					<HowCard
						icon={<FiMessageCircle />}
						title={t("studio.how.1.title", { defaultValue: "Просто расскажите" })}
						text={t("studio.how.1.text", {
							defaultValue: "Напишите своими словами, что хотите — как другу.",
						})}
					/>
					<HowCard
						icon={<FiZap />}
						title={t("studio.how.2.title", { defaultValue: "ИИ всё сделает" })}
						text={t("studio.how.2.text", {
							defaultValue: "Искусственный интеллект придумает, нарисует и оживит.",
						})}
					/>
					<HowCard
						icon={<FiSmile />}
						title={t("studio.how.3.title", { defaultValue: "Готово!" })}
						text={t("studio.how.3.text", {
							defaultValue: "Сохраните результат и покажите близким.",
						})}
					/>
				</div>

				{/* Финальный призыв — сразу к первому шагу. */}
				<div className="mt-12 text-center">
					<a
						href="#step-1"
						className="inline-flex items-center gap-2 rounded-2xl bg-accent px-7 py-4 text-lg font-bold text-on-accent shadow-lg shadow-accent/20 hover:bg-accent-strong transition-colors"
					>
						<FiPlay /> {t("studio.cta_final", { defaultValue: "Начать с первого шага" })}
					</a>
				</div>
			</section>
		</main>
	);
}

/* ---------- Коннектор между шагами (стрелка) ---------- */
function Connector() {
	return (
		<div className="flex items-center justify-center" aria-hidden>
			{/* Десктоп — стрелка вправо, мобайл — вниз. */}
			<span className="hidden lg:grid place-items-center h-10 w-10 rounded-full border border-border bg-surface-2 text-accent">
				<FiArrowRight />
			</span>
			<span className="grid lg:hidden place-items-center h-9 w-9 rounded-full border border-border bg-surface-2 text-accent">
				<FiChevronDown />
			</span>
		</div>
	);
}

/* ---------- «Скоро» карточка ---------- */
function SoonCard({
	emoji,
	icon,
	title,
	subtitle,
}: {
	emoji: string;
	icon: React.ReactNode;
	title: string;
	subtitle: string;
}) {
	const { t } = useTranslation("common");
	return (
		<div className="relative rounded-2xl border border-border bg-surface/60 p-5 opacity-70">
			<span className="absolute right-4 top-4 rounded-full border border-accent/40 bg-accent-soft px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-accent">
				{t("studio.soon.badge", { defaultValue: "Скоро" })}
			</span>
			<div className="flex items-center gap-3">
				<span className="grid h-12 w-12 place-items-center rounded-xl bg-surface-2 text-2xl">
					{emoji}
				</span>
				<div className="min-w-0">
					<div className="flex items-center gap-1.5 text-base font-semibold text-foreground">
						<span className="text-muted">{icon}</span>
						{title}
					</div>
					<p className="mt-0.5 text-sm text-muted leading-snug">{subtitle}</p>
				</div>
			</div>
		</div>
	);
}

/* ---------- «Как это работает» карточка ---------- */
function HowCard({
	icon,
	title,
	text,
}: {
	icon: React.ReactNode;
	title: string;
	text: string;
}) {
	return (
		<div className="rounded-2xl border border-border bg-surface p-6 text-center">
			<span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-accent-soft text-2xl text-accent">
				{icon}
			</span>
			<h3 className="mt-4 text-lg font-semibold text-foreground">{title}</h3>
			<p className="mt-1.5 text-sm text-muted leading-relaxed">{text}</p>
		</div>
	);
}
