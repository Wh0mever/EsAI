"use client";

import React, { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";

// ==== Types ====
type PlanDTO = {
	id: number;
	period: "monthly" | "yearly";
	duration_days: number;
	is_free: boolean;
	is_active: boolean;
	sort_order: number;

	price_amount: string;
	price_base_amount: string | null;

	has_discount?: boolean;
	discount_percent?: number;

	llm_engine_id: string | null;

	ai_templates_limit: number | null;
	operations_per_month_limit: number | null;
	covers_limit: number | null;

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
	rewriter_enabled: boolean;
	antiplag_enabled: boolean;
	images_enabled: boolean;
	diffusion_images_enabled: boolean;
	blog_master_enabled: boolean;
	music_enabled: boolean;
	tts_enabled: boolean;
	my_templates_enabled: boolean;
	manager_enabled: boolean;
	support_enabled: boolean;

	can_purchase_addons: boolean;

	price_amount_rub?: number | null;
	price_amount_kgs?: number | null;
	price_base_amount_rub?: number | null;
	price_base_amount_kgs?: number | null;
};

type Currency = "USD" | "RUB" | "KGS";

// ==== Utils ====
// localStorage currency
function getPreferredCurrency(): Currency {
	if (typeof window === "undefined") return "USD";
	const v = window.localStorage.getItem("APP_CURRENCY");
	return v === "RUB" || v === "KGS" || v === "USD" ? v : "USD";
}

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
	// KGS visual fallback (no ISO code in Intl for symbol)
	return `${Math.round(num).toLocaleString(locale)} с̲`;
}

// unlimited label
function limitLabel(value: number | null | undefined, unlimited: string) {
	if (value === null || value === 0) return unlimited;
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
	const rows: Array<{ ok: boolean; content: React.ReactNode }> = [];

	if (plan.llm_engine_id) {
		rows.push({
			ok: true,
			content: (
				<p>
					<span className="text-yellow-400 font-bold">{plan.llm_engine_id} </span>
					{t("pricing.features.open_ai_model")}
				</p>
			),
		});
	}

	rows.push({
		ok: true,
		content: (
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.ai_templates_limit, unlimited)} </span>
				{t("pricing.features.ai_templates")}
			</p>
		),
	});

	rows.push({
		ok: true,
		content: (
			<p>
				<span className="text-yellow-400 font-bold">
					{limitLabel(plan.operations_per_month_limit, unlimited)}{" "}
				</span>
				{t("pricing.features.ops_per_month")}
			</p>
		),
	});

	rows.push({
		ok: true,
		content: (
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.covers_limit, unlimited)} </span>
				{t("pricing.features.covers")}
			</p>
		),
	});

	const toggles: Array<[boolean, string]> = [
		[plan.ai_chat_enabled, t("pricing.features.ai_chat")],
		[plan.realtime_chat_enabled, t("pricing.features.realtime_chat")],
		[plan.rewriter_enabled, t("pricing.features.rewriter")],
		[plan.antiplag_enabled, t("pricing.features.antiplag")],
		[plan.images_enabled, t("pricing.features.ai_images")],
		[plan.diffusion_images_enabled, t("pricing.features.diffusion_images")],
		[plan.blog_master_enabled, t("pricing.features.blog_master")],
		[plan.music_enabled, t("pricing.features.music")],
		[plan.tts_enabled, t("pricing.features.tts")],
		[plan.my_templates_enabled, t("pricing.features.my_templates")],
		[plan.manager_enabled, t("pricing.features.manager")],
		[plan.support_enabled, t("pricing.features.support")],
	];

	toggles.forEach(([ok, label]) => rows.push({ ok, content: <p>{label}</p> }));

	return (
		<ul className="flex flex-col gap-4 text-sm">
			{rows.map((r, i) => (
				<li key={i} className="flex items-center gap-3">
					{r.ok ? <Check /> : <Cross />}
					{r.content}
				</li>
			))}
		</ul>
	);
}

function PlanPrice({ plan, currency, t }: { plan: PlanDTO; currency: Currency; t: (k: string) => string }) {
	const { amount, base } = useMemo(() => pickPrices(plan, currency), [plan, currency]);
	const price = useMemo(() => formatMoney(amount, currency), [amount, currency]);
	const baseFmt = useMemo(() => (base != null ? formatMoney(base, currency) : null), [base, currency]);

	if (plan.is_free) return <h2 className="text-4xl font-bold text-center">{t("pricing.free")}</h2>;

	if (baseFmt) {
		return (
			<div className="flex gap-3 items-center justify-center">
				<h2 className="text-4xl font-bold text-gray-300">{price}</h2>
				<span className="text-xs px-2 py-1 rounded bg-neutral-800 line-through text-gray-500">{baseFmt}</span>
			</div>
		);
	}
	return <h2 className="text-4xl font-bold text-gray-300 text-center">{price}</h2>;
}

function PlanCard({
	plan,
	title,
	subtitle,
	t,
	currency,
}: {
	plan: PlanDTO;
	title: string;
	subtitle?: string;
	t: (k: string) => string;
	currency: Currency;
}) {
	return (
		<div className="w-full bg-black rounded-3xl border border-gray-800 p-8 flex flex-col gap-6 justify-between relative max-w-[400px]">
			{/* decorative line */}
			<img
				src="/images/decorations/pricing-5-card-line.webp"
				alt=""
				className="pointer-events-none select-none absolute inset-0 w-full h-full object-contain opacity-20"
			/>

			<div className="flex flex-col gap-4 relative">
				<p className="text-center text-color-on-hover">{title}</p>
				{subtitle ? <p className="text-gray-400 text-center">{subtitle}</p> : null}
				<PlanPrice plan={plan} currency={currency} t={t} />
				<PlanFeatures plan={plan} t={t} />
			</div>

			<div className="flex justify-center relative">
				<Button
					onClick={() => {}}
					className="select-text mt-3 py-2 px-4 rounded-lg bg-indigo-500 hover:bg-indigo-600 duration-300"
				>
					{t("pricing.startofwork")}
				</Button>
			</div>
		</div>
	);
}

// ==== Tabs ====
function PlansGrid({
	active,
	plans,
	t,
	currency,
	titleKind,
}: {
	active: boolean;
	plans: PlanDTO[];
	t: (k: string) => string;
	currency: Currency;
	titleKind: "monthly" | "yearly";
}) {
	if (!active) return null;
	return (
		<div className={clsx("grid gap-5 w-full", "[grid-template-columns:repeat(auto-fit,minmax(280px,360px))]")}>
			{plans.map((p) => (
				<PlanCard
					key={p.id}
					plan={p}
					t={t}
					currency={currency}
					title={p.is_free ? t("pricing.vokalo_test") : t(`pricing.${titleKind}`)}
					subtitle={p.is_free ? t("pricing.test_subtitle") : t(`pricing.${titleKind}_subtitle`)}
				/>
			))}
		</div>
	);
}

// ==== Root ====
export default function PricingTab() {
	const { t } = useTranslation("common");
	const [activeTab, setActiveTab] = useState<0 | 1>(0);
	const [currency, setCurrency] = useState<Currency>("USD");
	const [monthlyPlans, setMonthlyPlans] = useState<PlanDTO[]>([]);
	const [yearlyPlans, setYearlyPlans] = useState<PlanDTO[]>([]);
	const [loading, setLoading] = useState(true);

	// currency init + listen external events
	useEffect(() => {
		setCurrency(getPreferredCurrency());
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

	// fetch data
	useEffect(() => {
		let mounted = true;
		(async () => {
			try {
				const [mResp, yResp] = await Promise.all([
					fetchData("plans/list/?period=monthly", "GET", undefined, false),
					fetchData("plans/list/?period=yearly", "GET", undefined, false),
				]);
				if (!mounted) return;
				setMonthlyPlans(Array.isArray(mResp?.data) ? mResp.data : []);
				setYearlyPlans(Array.isArray(yResp?.data) ? yResp.data : []);
			} catch (e) {
				console.error("Failed to load plans", e);
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

	const hasData = monthlyPlans.length > 0 || yearlyPlans.length > 0;

	return (
		<div className="w-full overflow-x-hidden select-none">
			{/* Header / tabs */}
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
						{t("pricing.monthly")}
					</Button>
					<Button
						className={clsx(
							"text-sm hover:text-indigo-500 duration-300",
							activeTab === 1 && "text-indigo-500 underline underline-offset-4"
						)}
						onClick={() => setActiveTab(1)}
					>
						{t("pricing.yearly")}
					</Button>
				</div>
				<p className="flex-auto border-b border-gray-800" />
			</div>

			{/* Content */}
			<div className="px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 pb-10">
				{loading && <div className="text-center text-gray-400 py-10">{t("pricing.loading")}</div>}
				{!loading && !hasData && (
					<div className="text-center text-gray-400 py-10">{t("pricing.nothing_found")}</div>
				)}
				{!loading && hasData && (
					<>
						<PlansGrid
							active={activeTab === 0}
							plans={monthlyPlans}
							t={t}
							currency={currency}
							titleKind="monthly"
						/>
						<PlansGrid
							active={activeTab === 1}
							plans={yearlyPlans}
							t={t}
							currency={currency}
							titleKind="yearly"
						/>
					</>
				)}
			</div>
		</div>
	);
}
