"use client";

import "@/assets/style.scss";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiFilm, FiUser, FiScissors, FiArrowRight } from "react-icons/fi";
import TokenPackages from "@/components/pricing/TokenPackages";
import CurrencySwitch from "@/components/pricing/CurrencySwitch";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import { useCurrency } from "@/hooks/useCurrency";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";

/**
 * Тарифы Cartoon Studio — отдельная витрина тех же разовых пакетов.
 *
 * Отдельная страница, а не блок на /pricing, по просьбе клиента: в студию
 * человек приходит с другим вопросом. Ему не важно, сколько это запросов к
 * нейросети, — ему важно, сколько мультфильмов он соберёт.
 *
 * Пакеты те же самые и кошелёк один: кредиты, купленные здесь, работают и в
 * чате. Придумывать «студийную валюту» значило бы делить баланс на два и
 * объяснять человеку, почему на одном экране кредиты есть, а на другом нет.
 *
 * Цены сцены и персонажа берутся с бэкенда (GET /api/cartoon/pricing/), а не
 * пишутся в вёрстке: коэффициенты моделей меняются в админке, и витрина не
 * должна расходиться с тем, что спишется на самом деле.
 */

type StudioPricing = {
	character: number;
	scene_min: number;
	scene_typical: number;
	scene_max: number;
};

/** Сцен в мультфильме «по умолчанию» — на них и считаем, сколько роликов выйдет. */
const SCENES_PER_MOVIE = 4;

export default function StudioPricing() {

	// Счётчик воронки: сколько людей вообще дошло до тарифов.
	useEffect(() => {
		trackFunnel("pricing_view");
	}, []);
	const { t } = useTranslation("common");
	const { currency, setCurrency, convert } = useCurrency();
	const [pricing, setPricing] = useState<StudioPricing | null>(null);

	useEffect(() => {
		let alive = true;
		(async () => {
			const res = await fetchData<StudioPricing>("cartoon/pricing/", "GET", null, false);
			if (alive && res.ok && res.data) setPricing(res.data);
		})();
		return () => {
			alive = false;
		};
	}, []);

	const scene = pricing?.scene_typical || 0;
	const character = pricing?.character || 0;

	return (
		<main className="pt-80 overflow-hidden relative">
			<Breadcrumb />

			<div className="flex flex-col items-center gap-8 px-6 lg:px-40">
				<header className="flex max-w-3xl flex-col items-center gap-3 text-center">
					<h1 className="text-3xl font-bold text-foreground sm:text-4xl">
						{t("studio_pricing.title", { defaultValue: "Тарифы Cartoon Studio" })}
					</h1>
					<p className="text-muted">
						{t("studio_pricing.subtitle", {
							defaultValue:
								"Разовые пакеты кредитов — без подписки и без списаний каждый месяц. Заплатили один раз, кредиты не сгорают и работают и в студии, и в чате.",
						})}
					</p>
				</header>

				{/* Из чего складывается счёт. Клиент просил показать математику
				    открыто — человек должен понимать, за что платит, до оплаты. */}
				<section className="w-full max-w-3xl rounded-2xl border border-border bg-surface p-6">
					<h2 className="text-lg font-semibold text-foreground">
						{t("studio_pricing.math_title", { defaultValue: "Из чего складывается стоимость" })}
					</h2>
					<div className="mt-4 grid gap-3 sm:grid-cols-3">
						<div className="flex flex-col gap-1 rounded-xl bg-surface-2 p-4">
							<FiUser className="text-xl text-accent" />
							<span className="text-sm text-muted">
								{t("studio_pricing.math_character", { defaultValue: "Свой герой" })}
							</span>
							<span className="text-lg font-bold text-foreground">
								{character
									? t("studio_pricing.credits", { count: character, defaultValue: "{{count}} кредитов" })
									: "—"}
							</span>
							<span className="text-xs text-muted-2">
								{t("studio_pricing.math_character_note", {
									defaultValue: "Из библиотеки — бесплатно",
								})}
							</span>
						</div>
						<div className="flex flex-col gap-1 rounded-xl bg-surface-2 p-4">
							<FiFilm className="text-xl text-accent" />
							<span className="text-sm text-muted">
								{t("studio_pricing.math_scene", { defaultValue: "Сцена 5 секунд" })}
							</span>
							<span className="text-lg font-bold text-foreground">
								{scene
									? t("studio_pricing.credits", { count: scene, defaultValue: "{{count}} кредитов" })
									: "—"}
							</span>
							<span className="text-xs text-muted-2">
								{t("studio_pricing.math_scene_note", {
									defaultValue: "Кадр с вашим героем плюс само видео",
								})}
							</span>
						</div>
						<div className="flex flex-col gap-1 rounded-xl bg-surface-2 p-4">
							<FiScissors className="text-xl text-accent" />
							<span className="text-sm text-muted">
								{t("studio_pricing.math_assembly", { defaultValue: "Склейка мультфильма" })}
							</span>
							<span className="text-lg font-bold text-foreground">
								{t("studio_pricing.math_free", { defaultValue: "Бесплатно" })}
							</span>
							<span className="text-xs text-muted-2">
								{t("studio_pricing.math_assembly_note", {
									defaultValue: "Сколько угодно раз, сцены не пересчитываются",
								})}
							</span>
						</div>
					</div>
					{scene > 0 && (
						<p className="mt-4 text-sm text-muted">
							{t("studio_pricing.math_example", {
								defaultValue:
									"Мультфильм из 4 сцен — это 20 секунд и {{total}} кредитов. Неудачная сцена пересобирается по цене одной сцены, остальные не трогаются.",
								total: scene * SCENES_PER_MOVIE,
							})}
						</p>
					)}
				</section>

				<CurrencySwitch value={currency} onChange={setCurrency} />

				<TokenPackages
					currency={currency}
					convert={convert}
					returnTo="/studio"
					valueOverride={(p) => {
						if (!scene) return null;
						const total = Number(p.tokens || 0) + Number(p.bonus_tokens || 0);
						const scenes = Math.floor(total / scene);
						if (scenes < 1) return null;
						const movies = Math.floor(scenes / SCENES_PER_MOVIE);
						const rows = [
							t("studio_pricing.value_scenes", {
								count: scenes,
								defaultValue: "🎬 {{count}} сцен по 5 секунд",
							}),
						];
						if (movies >= 1) {
							rows.push(
								t("studio_pricing.value_movies", {
									count: movies,
									defaultValue: "🎞 {{count}} мультфильмов по 20 секунд",
								})
							);
						}
						// Не «сколько героев поместится»: делением пакета на цену героя
						// выходят абсурдные семьсот штук, и вся прикидка теряет смысл.
						if (character > 0) {
							rows.push(
								t("studio_pricing.value_characters", {
									count: character,
									defaultValue: "🦸 Плюс свои герои — по {{count}} кредита",
								})
							);
						}
						return {
							title: t("studio_pricing.value_title", { defaultValue: "Хватит на" }),
							rows,
						};
					}}
				/>

				<p className="-mt-4 px-4 text-center text-sm text-muted">
					💡{" "}
					<span className="font-semibold text-accent-strong">
						{t("packages.no_expiry_highlight", { defaultValue: "Кредиты не сгорают" })}
					</span>
					.{" "}
					{t("studio_pricing.same_wallet", {
						defaultValue: "Один баланс на всё: студия, чат, картинки и видео.",
					})}
				</p>

				<div className="mb-16 flex flex-col items-center gap-3">
					<Link
						href="/studio"
						className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-3 font-semibold text-on-accent transition-colors hover:bg-accent-strong"
					>
						{t("studio_pricing.back_to_studio", { defaultValue: "Вернуться в студию" })}
						<FiArrowRight />
					</Link>
					<Link href="/pricing" className="text-sm text-muted hover:text-foreground">
						{t("studio_pricing.all_packages", { defaultValue: "Все тарифы EsAI" })}
					</Link>
				</div>
			</div>
		</main>
	);
}
