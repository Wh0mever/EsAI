"use client";

import React, { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { Button } from "@/components/ui/buttons/Buttons";
import NextLink from "../nextLink/NextLink";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { IoVideocamOutline } from "react-icons/io5";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { getInitialCurrency } from "@/lib/currency";
import Cookies from "js-cookie";

// ==== Types ====
type PlanDTO = {
	id: number;
	period: "weekly" | "monthly" | "yearly";
	is_free: boolean;
	is_active: boolean;
	sort_order: number;

	price_amount: string;
	price_base_amount: string | null;

	has_discount?: boolean;
	discount_percent?: number;

	llm_engine_id: string | null;
	llm_engine_name?: string | null;

	song_limit: number;
	music_limit: number;
	text_limit: number;
	image_limit: number;

	sunday_bonus_songs: number;
	sunday_bonus_music: number;
	sunday_bonus_texts: number;
	sunday_bonus_images: number;

	ai_chat_enabled: boolean;
	realtime_chat_enabled: boolean;
	images_enabled: boolean;
	music_enabled: boolean;
	support_enabled: boolean;
	mp4_enabled: boolean;

	can_purchase_addons: boolean;

	price_amount_rub?: number | null;
	price_amount_kgs?: number | null;
	price_base_amount_rub?: number | null;
	price_base_amount_kgs?: number | null;

	// titles by language
	template_name_ru?: string | null;
	template_name_en?: string | null;
	template_name_kg?: string | null;
};

type Currency = "USD" | "RUB" | "KGS";

// ==== Utils ====
// localStorage currency
// initial currency from localStorage -> cookie -> hostname
function getPreferredCurrency(): Currency { return getInitialCurrency(); }

// number formatting per currency
function formatMoney(amount: number | string | null | undefined, currency: Currency, locale = "ru-RU") {
	if (amount == null) return "";
	const num = typeof amount === "string" ? parseFloat(amount) : amount;
	if (!Number.isFinite(num)) return "";

	if (currency === "USD") {
		try {
			return new Intl.NumberFormat(locale, {
				style: "currency",
				currency: "USD",
				maximumFractionDigits: 2,
			}).format(num);
		} catch {
			return `$ ${num.toFixed(2)}`;
		}
	}
	if (currency === "RUB") {
		try {
			return new Intl.NumberFormat(locale, {
				style: "currency",
				currency: "RUB",
				maximumFractionDigits: 0,
			}).format(num);
		} catch {
			return `${Math.round(num).toLocaleString(locale)} ₽`;
		}
	}
	return `${Math.round(num).toLocaleString(locale)} с̲`;
}

// unlimited label
function limitLabel(value: number | null | undefined, unlimited: string) {
	if (value === null || value === undefined) return unlimited;
	return String(value);
}

// derived prices
function pickPrices(plan: PlanDTO, currency: Currency) {
	const usdAmount = plan.price_amount ? parseFloat(plan.price_amount) : null;
	const usdBase = plan.price_base_amount ? parseFloat(plan.price_base_amount) : null;

	if (currency === "RUB") {
		return {
			amount: plan.price_amount_rub ?? usdAmount,
			base: plan.price_base_amount_rub ?? usdBase,
		};
	}
	if (currency === "KGS") {
		return {
			amount: plan.price_amount_kgs ?? usdAmount,
			base: plan.price_base_amount_kgs ?? usdBase,
		};
	}
	return { amount: usdAmount, base: usdBase };
}

// select localized title
function selectPlanTitle(plan: PlanDTO, lang: "ru" | "en" | "kg"): string | undefined {
	const map: Record<string, string | null | undefined> = {
		ru: plan.template_name_ru,
		en: plan.template_name_en,
		kg: plan.template_name_kg,
	};
	return (
		(map[lang] || plan.template_name_ru || plan.template_name_en || plan.template_name_kg || undefined) ?? undefined
	);
}

// ==== Small UI bits ====
function Check() {
	return (
		<i className="grid place-items-center w-5 h-5 rounded-full bg-green-500 text-black">
			<IoIosCheckmark />
		</i>
	);
}
function Cross() {
	return (
		<i className="grid place-items-center w-5 h-5 rounded-full bg-red-500 text-black">
			<IoIosClose />
		</i>
	);
}

function PlanFeatures({ plan, t }: { plan: PlanDTO; t: (k: string) => string }) {
	const unlimited = t("pricing.unlimited");
	const counters: Array<React.ReactNode> = [];
	const bonusRows: Array<React.ReactNode> = [];

	counters.push(
		<li key="songs" className="flex items-center gap-3">
			<Check />
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.song_limit, unlimited)} </span>
				{t("pricing.features.songs_count")}
			</p>
		</li>
	);
	counters.push(
		<li key="images" className="flex items-center gap-3">
			<Check />
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.image_limit, unlimited)} </span>
				{t("pricing.features.images_count")}
			</p>
		</li>
	);
	counters.push(
		<li key="music" className="flex items-center gap-3">
			<Check />
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.music_limit, unlimited)} </span>
				{t("pricing.features.music_count")}
			</p>
		</li>
	);

	if ((plan.sunday_bonus_songs || 0) > 0) {
		bonusRows.push(
			<li key="bonus-songs" className="pl-8 text-yellow-300">
				+{plan.sunday_bonus_songs} {t("pricing.features.sunday_bonus_songs")}
			</li>
		);
	}
	if ((plan.sunday_bonus_music || 0) > 0) {
		bonusRows.push(
			<li key="bonus-music" className="pl-8 text-yellow-300">
				+{plan.sunday_bonus_music} {t("pricing.features.sunday_bonus_music")}
			</li>
		);
	}
	if ((plan.sunday_bonus_texts || 0) > 0) {
		bonusRows.push(
			<li key="bonus-texts" className="pl-8 text-yellow-300">
				+{plan.sunday_bonus_texts} {t("pricing.features.sunday_bonus_texts")}
			</li>
		);
	}
	if ((plan.sunday_bonus_images || 0) > 0) {
		bonusRows.push(
			<li key="bonus-images" className="pl-8 text-yellow-300">
				+{plan.sunday_bonus_images} {t("pricing.features.sunday_bonus_images")}
			</li>
		);
	}

	const toggles: Array<{ ok: boolean; label: string; key: "mp4" | "support" }> = [
		{ ok: plan.mp4_enabled, label: t("pricing.features.mp4"), key: "mp4" },
		{ ok: plan.support_enabled, label: t("pricing.features.support"), key: "support" },
	];

	return (
		<ul className="flex flex-col gap-3 text-sm">
			{counters}
			{bonusRows.length > 0 && (
				<li className="flex items-start gap-3">
					<Check />
					<div>
						<p>{t("pricing.features.sunday_bonus_title")}</p>
						<ul className="mt-1 flex flex-col gap-1">{bonusRows}</ul>
					</div>
				</li>
			)}
			{toggles.map((row, i) => (
				<li key={`toggle-${i}`} className="flex items-center gap-3">
					{row.ok ? <Check /> : <Cross />}
					<p className="inline-flex items-center gap-2">
						{row.key === "mp4" && <IoVideocamOutline className="text-red-300" />}
						{row.label}
					</p>
				</li>
			))}
		</ul>
	);
}

function PlanPrice({ plan, currency, t }: { plan: PlanDTO; currency: Currency; t: (k: string) => string }) {
	const { amount, base } = useMemo(() => pickPrices(plan, currency), [plan, currency]);
	const price = useMemo(() => formatMoney(amount, currency), [amount, currency]);
	const baseFmt = useMemo(() => (base != null ? formatMoney(base, currency) : null), [base, currency]);

	if (plan.is_free) return <h2 className="text-3xl font-bold text-center">{t("pricing.free")}</h2>;

	if (baseFmt) {
		return (
			<div className="flex gap-3 items-center justify-center">
				<h2 className="text-3xl font-bold text-center text-gray-300">{price}</h2>
				<span className="text-xs px-2 py-1 rounded bg-neutral-800 line-through text-gray-500">{baseFmt}</span>
			</div>
		);
	}
	return <h2 className="text-3xl font-bold text-center text-gray-300">{price}</h2>;
}

function PlanCard({
	plan,
	title,
	subtitle,
	t,
	currency,
	authed,
}: {
	plan: PlanDTO;
	title: string;
	subtitle?: string;
	t: (k: string) => string;
	currency: Currency;
	authed: boolean;
}) {
	return (
		<div className="w-full bg-black rounded-3xl border border-gray-800 p-8 flex flex-col gap-6 justify-between relative max-w-full sm:max-w-[400px]">
			<img
				src="/images/decorations/pricing-5-card-line.webp"
				alt=""
				className="pointer-events-none select-none absolute inset-0 w-full h-full object-contain opacity-20"
			/>

			<div className="flex flex-col gap-4 relative">
				<p className="text-center text-color-on-hover text-lg">{title}</p>
				{subtitle ? <p className="text-gray-400 text-center">{subtitle}</p> : null}
				<PlanPrice plan={plan} currency={currency} t={t} />
				<PlanFeatures plan={plan} t={t} />
			</div>

			<div className="flex justify-center relative">
				{!authed ? (
					<NextLink
						href="/auth/signup"
						className="select-text mt-3 py-2 px-4 rounded-lg bg-indigo-500 hover:bg-indigo-600 duration-300"
					>
						{t("pricing.try_now")}
					</NextLink>
				) : plan.is_free ? null : (
					<NextLink
						href={`subscribe/${plan.id}/`}
						className="select-text mt-3 py-2 px-4 rounded-lg bg-indigo-500 hover:bg-indigo-600 duration-300"
					>
						{t("pricing.startofwork")}
					</NextLink>
				)}
			</div>
		</div>
	);
}

// ==== Tabs ====
function PlansCarousel({
	plans,
	t,
	currency,
	lang,
	authed,
}: {
	plans: PlanDTO[];
	t: (k: string) => string;
	currency: Currency;
	lang: "ru" | "en" | "kg";
	authed: boolean;
}) {
	const listRef = React.useRef<HTMLDivElement | null>(null);
	const [idx, setIdx] = React.useState(0);

	const scrollTo = (i: number) => {
		const el = listRef.current;
		if (!el) return;
		const children = Array.from(el.children) as HTMLElement[];
		const target = children[i];
		if (!target) return;
		el.scrollTo({ left: target.offsetLeft - 16, behavior: "smooth" });
		setIdx(i);
	};

	const onPrev = () => scrollTo(Math.max(0, idx - 1));
	const onNext = () => scrollTo(Math.min(plans.length - 1, idx + 1));

	// Update active index on user scroll
	React.useEffect(() => {
		const el = listRef.current;
		if (!el) return;
		const onScroll = () => {
			const children = Array.from(el.children) as HTMLElement[];
			let best = 0;
			let bestDist = Infinity;
			const center = el.scrollLeft + el.clientWidth / 2;
			children.forEach((c, i) => {
				const mid = c.offsetLeft + c.offsetWidth / 2;
				const d = Math.abs(mid - center);
				if (d < bestDist) {
					bestDist = d;
					best = i;
				}
			});
			setIdx(best);
		};
		el.addEventListener("scroll", onScroll, { passive: true });
		return () => el.removeEventListener("scroll", onScroll as any);
	}, []);

	return (
		<div className="relative sm:hidden">
			<div className="flex items-center justify-between mb-3 px-1">
				<button
					onClick={onPrev}
					className="px-3 py-1 rounded-md bg-neutral-900 border border-white/10 text-sm disabled:opacity-40"
					disabled={idx <= 0}
				>
					{t("common.prev") || "Prev"}
				</button>
				<div className="text-xs text-neutral-400">
					{idx + 1} / {plans.length}
				</div>
				<button
					onClick={onNext}
					className="px-3 py-1 rounded-md bg-neutral-900 border border-white/10 text-sm disabled:opacity-40"
					disabled={idx >= plans.length - 1}
				>
					{t("common.next") || "Next"}
				</button>
			</div>

			<div
				ref={listRef}
				className="flex gap-4 overflow-x-auto scroll-smooth snap-x snap-mandatory px-1 pb-2"
				style={{ scrollPaddingLeft: 16, scrollPaddingRight: 16 }}
			>
				{plans.map((p) => {
					const localized = selectPlanTitle(p, lang);
					const fallback = p.is_free ? t("pricing.vokalo_test") : t(`pricing.${p.period}`);
					const title = localized && localized.trim().length > 0 ? localized : fallback;
					const subtitle = p.is_free ? t("pricing.test_subtitle") : t(`pricing.${p.period}_subtitle`);
					return (
						<div key={p.id} className="snap-start shrink-0 w-full min-w-[88%]">
							<PlanCard plan={p} t={t} currency={currency} title={title} subtitle={subtitle} authed={authed} />
						</div>
					);
				})}
			</div>
		</div>
	);
}

function PlansGrid({
	active,
	plans,
	t,
	currency,
	lang,
	authed,
}: {
	active: boolean;
	plans: PlanDTO[];
	t: (k: string) => string;
	currency: Currency;
	lang: "ru" | "en" | "kg";
	authed: boolean;
}) {
	if (!active) return null;

	return (
		<>
			{/* Mobile: slider */}
			<PlansCarousel plans={plans} t={t} currency={currency} lang={lang} authed={authed} />
			{/* Desktop: grid */}
			<div
				className={clsx(
					"hidden sm:grid gap-5 w-full justify-center",
					"[grid-template-columns:repeat(auto-fit,minmax(280px,360px))]"
				)}
			>
				{plans.map((p) => {
					const localized = selectPlanTitle(p, lang);
					const fallback = p.is_free ? t("pricing.vokalo_test") : t(`pricing.${p.period}`);
					const title = localized && localized.trim().length > 0 ? localized : fallback;

					const subtitle = p.is_free ? t("pricing.test_subtitle") : t(`pricing.${p.period}_subtitle`);

					return <PlanCard key={p.id} plan={p} t={t} currency={currency} title={title} subtitle={subtitle} authed={authed} />;
				})}
			</div>
		</>
	);
}

// ==== Root ====
export default function PricingTab() {
	const { t, i18n } = useTranslation("common");
	const [activeTab, setActiveTab] = useState<0 | 1 | 2>(0);
	const [currency, setCurrency] = useState<Currency>(() => (typeof window !== "undefined" ? getInitialCurrency() : "USD"));
	const [authed, setAuthed] = useState(false);
	const [allPlans, setAllPlans] = useState<PlanDTO[]>([]);
	const [monthlyPlans, setMonthlyPlans] = useState<PlanDTO[]>([]);
	const [yearlyPlans, setYearlyPlans] = useState<PlanDTO[]>([]);
	const [loading, setLoading] = useState(true);

	const lang = useMemo<"ru" | "en" | "kg">(
		() => (i18n.language ?? "ru").split("-")[0] as "ru" | "en" | "kg",
		[i18n.language]
	);

	useEffect(() => {
		setCurrency(getPreferredCurrency());
		setAuthed(Boolean(Cookies.get("access")));
		const handle = (e: Event) => {
			try {
				// @ts-ignore
				const code = e?.detail?.code as Currency | undefined;
				if (code) setCurrency(code);
				else {
					const saved = window.localStorage.getItem("APP_CURRENCY") as Currency | null;
					if (saved === "USD" || saved === "RUB" || saved === "KGS") setCurrency(saved);
				}
			} catch {}
		};
		window.addEventListener("app:currency-changed", handle as EventListener);
		return () => window.removeEventListener("app:currency-changed", handle as EventListener);
	}, []);

	useEffect(() => {
		let mounted = true;
		(async () => {
			try {
				const [allResp, mResp, yResp] = await Promise.all([
					fetchData("plans/list/", "GET", undefined, false),
					fetchData("plans/list/?period=monthly", "GET", undefined, false),
					fetchData("plans/list/?period=yearly", "GET", undefined, false),
				]);
				if (!mounted) return;
				setAllPlans(Array.isArray(allResp?.data) ? allResp.data : []);
				setMonthlyPlans(Array.isArray(mResp?.data) ? mResp.data : []);
				setYearlyPlans(Array.isArray(yResp?.data) ? yResp.data : []);
			} catch (e) {
				console.error("Failed to load plans", e);
				setAllPlans([]);
				setMonthlyPlans([]);
				setYearlyPlans([]);
			} finally {
				mounted && setLoading(false);
			}
		})();
		return () => {
			mounted = false;
		};
	}, []);

	const hasData = allPlans.length > 0 || monthlyPlans.length > 0 || yearlyPlans.length > 0;

	return (
		<div className="w-full overflow-x-hidden select-none">
			<div className="flex items-center gap-6 px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 py-10">
				<p className="flex-auto border-b border-gray-800" />
				<div className="flex bg-neutral-900 rounded-xl border border-gray-700 px-4 sm:px-6 py-3 gap-6">
					<Button
						className={clsx(
							"text-sm hover:text-indigo-500 duration-300",
							activeTab === 0 && "text-indigo-500 underline underline-offset-4"
						)}
						onClick={() => setActiveTab(0)}
					>
						{t("pricing.all")}
					</Button>
					<Button
						className={clsx(
							"text-sm hover:text-indigo-500 duration-300",
							activeTab === 1 && "text-indigo-500 underline underline-offset-4"
						)}
						onClick={() => setActiveTab(1)}
					>
						{t("pricing.monthly")}
					</Button>
					<Button
						className={clsx(
							"text-sm hover:text-indigo-500 duration-300",
							activeTab === 2 && "text-indigo-500 underline underline-offset-4"
						)}
						onClick={() => setActiveTab(2)}
					>
						{t("pricing.yearly")}
					</Button>
				</div>
				<p className="flex-auto border-b border-gray-800" />
			</div>

			<div className="px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 pb-10">
				{loading && <div className="text-center text-gray-400 py-10">{t("pricing.loading")}</div>}
				{!loading && !hasData && (
					<div className="text-center text-gray-400 py-10">{t("pricing.nothing_found")}</div>
				)}
				{!loading && hasData && (
					<>
						<PlansGrid
							active={activeTab === 0}
							plans={allPlans}
							t={t}
							currency={currency}
							lang={lang}
							authed={authed}
						/>
						<PlansGrid
							active={activeTab === 1}
							plans={monthlyPlans}
							t={t}
							currency={currency}
							lang={lang}
							authed={authed}
						/>
						<PlansGrid
							active={activeTab === 2}
							plans={yearlyPlans}
							t={t}
							currency={currency}
							lang={lang}
							authed={authed}
						/>
					</>
				)}
			</div>
		</div>
	);
}
