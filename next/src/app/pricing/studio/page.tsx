"use client";

import "@/assets/style.scss";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiFilm, FiUser, FiScissors, FiArrowLeft } from "react-icons/fi";
import TokenPackages from "@/components/pricing/TokenPackages";
import CurrencySwitch from "@/components/pricing/CurrencySwitch";
import { PackagePickerHead } from "@/components/pricing/PackageCarousel";
import { useCurrency } from "@/hooks/useCurrency";
import { useBalance } from "@/hooks/useBalance";
import { parseNeed } from "@/lib/packagePick";
import type { PackageNeed } from "@/lib/packagePick";
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
 *
 * С 05.11.2026 сверху сразу выбор пакета — та же карусель, что в видеостудии
 * (клиент: до тарифов приходилось долго листать). Пришли из «Снять» с
 * нехваткой (?need=12&cost=63&for=scene) — первым стоит самый дешёвый пакет,
 * которого хватит, а «на что хватит» считается по цене этой самой сцены.
 * «Из чего складывается стоимость» — ниже тарифов.
 */

type StudioPricing = {
	character: number;
	scene_min: number;
	scene_typical: number;
	scene_max: number;
	/** С чем снимается новый мультфильм: settings — настройки по умолчанию из админки
	 *  (Seedance Mini 480p 5 с), preset — откат на сцены библиотеки. Цены выше — по ним. */
	settings?: {
		video_model: string | null;
		model_name?: string;
		resolution: string | null;
		duration: number | null;
		source: string;
	};
};

/** Сцен в мультфильме «по умолчанию» — на них и считаем, сколько роликов выйдет. */
const SCENES_PER_MOVIE = 4;

export default function StudioPricing() {

	// Счётчик воронки: сколько людей вообще дошло до тарифов.
	useEffect(() => {
		trackFunnel("pricing_view");
	}, []);
	const { t } = useTranslation("common");
	const { currency, setCurrency, convert, format, cryptoEnabled } = useCurrency();
	const [pricing, setPricing] = useState<StudioPricing | null>(null);
	const [need, setNeed] = useState<PackageNeed | null>(null);
	const { balance } = useBalance();

	// Адрес читаем после монтирования: страница отдаётся статикой, и нехватка
	// известна только в браузере.
	useEffect(() => {
		setNeed(parseNeed(window.location.search));
	}, []);

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

	// Пришли со съёмки конкретной сцены — считаем по её цене: она и спишется.
	const fromScene = need?.for === "scene" && need.cost > 0;
	const scene = (fromScene && need ? need.cost : 0) || pricing?.scene_typical || 0;
	const seconds = pricing?.settings?.duration || 5;
	// «от N кр» — самая дешёвая сцена НОВОГО мультфильма (как его снимет студия).
	const sceneFrom = pricing?.scene_min || 0;
	const character = pricing?.character || 0;
	const defaults = pricing?.settings?.source === "settings" ? pricing.settings : null;

	return (
		<main className="relative overflow-hidden pt-24 pb-10">
			<div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4">
				<PackagePickerHead
					as="h1"
					need={need}
					switcher={<CurrencySwitch value={currency} onChange={setCurrency} cryptoEnabled={cryptoEnabled} />}
				/>

				<TokenPackages
					currency={currency}
					convert={convert}
					format={format}
					returnTo="/studio"
					layout="carousel"
					need={need}
					valueOverride={(p) => {
						if (!scene) return null;
						const total = Number(p.tokens || 0) + Number(p.bonus_tokens || 0);
						const scenes = Math.floor(total / scene);
						if (scenes < 1) return null;
						const movies = Math.floor(scenes / SCENES_PER_MOVIE);
						// Цена пришла со съёмки — длительность той сцены нам неизвестна,
						// поэтому «таких сцен», а не «по 5 секунд».
						const rows = [
							fromScene
								? t("pkg_picker.scenes_like", { count: scenes, defaultValue: "{{count}} таких сцен" })
								: t("studio_pricing.value_scenes", {
										count: scenes,
										seconds,
										defaultValue: "🎬 {{count}} сцен по {{seconds}} секунд",
									}),
						];
						if (movies >= 1) {
							rows.push(
								t("studio_pricing.value_movies", {
									count: movies,
									seconds: seconds * SCENES_PER_MOVIE,
									defaultValue: "🎞 {{count}} мультфильмов по {{seconds}} секунд",
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

				<div className="flex items-center justify-between gap-3 border-t border-border pt-4 text-sm">
					<Link href="/studio" className="inline-flex items-center gap-1.5 text-muted transition-colors hover:text-foreground">
						<FiArrowLeft />
						{t("studio_pricing.back_to_studio", { defaultValue: "Вернуться в студию" })}
					</Link>
					{balance != null && (
						<span className="font-semibold text-accent-strong">
							{t("pkg_picker.balance", { defaultValue: "Баланс {{amount}} кр.", amount: balance })}
						</span>
					)}
				</div>

				{/* Из чего складывается счёт. Клиент просил показать математику
				    открыто — человек должен понимать, за что платит, до оплаты. */}
				<section className="w-full rounded-2xl border border-border bg-surface p-6">
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
								{defaults?.duration
									? t("studio_pricing.math_scene_seconds", {
											defaultValue: "Сцена {{seconds}} с",
											seconds: defaults.duration,
										})
									: t("studio_pricing.math_scene", { defaultValue: "Сцена 5 секунд" })}
							</span>
							<span className="text-lg font-bold text-foreground">
								{sceneFrom
									? t("studio_pricing.scene_from", { defaultValue: "от {{credits}} кр", credits: sceneFrom })
									: "—"}
							</span>
							<span className="text-xs text-muted-2">
								{t("studio_pricing.math_scene_note", {
									defaultValue: "Кадр с вашим героем плюс само видео",
								})}
							</span>
							{/* Чем снимается новый мультфильм — от этого и цена. В студии всё
							    меняется в доке внизу, поэтому «от»: дороже модель — дороже сцена. */}
							{defaults?.model_name && defaults.resolution && (
								<span className="text-xs text-muted-2">
									{t("studio_pricing.math_scene_settings", {
										defaultValue: "{{model}} · {{resolution}} по умолчанию — модель, качество и длительность меняются в студии",
										model: defaults.model_name,
										resolution: defaults.resolution,
									})}
								</span>
							)}
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
								total: (pricing?.scene_typical || scene) * SCENES_PER_MOVIE,
							})}
						</p>
					)}
				</section>

				<p className="text-center text-sm text-muted">
					{t("studio_pricing.same_wallet", {
						defaultValue: "Один баланс на всё: студия, чат, картинки и видео.",
					})}{" "}
					<Link href="/pricing" className="underline hover:text-foreground">
						{t("studio_pricing.all_packages", { defaultValue: "Все тарифы EsAI" })}
					</Link>
				</p>
			</div>
		</main>
	);
}
