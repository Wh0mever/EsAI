"use client";

import "./PricingTab.scss";
import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";

// Типы приходящих данных
type PlanDTO = {
	id: number;
	period: "monthly" | "yearly";
	duration_days: number;
	is_free: boolean;
	is_active: boolean;
	sort_order: number;

	price_amount: string; // USD как строка
	price_base_amount: string | null;

	has_discount?: boolean;
	discount_percent?: number;

	// на бэке стало строкой (пример: "GPT - 5o")
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

	// новые цены
	price_amount_rub?: number | null;
	price_amount_kgs?: number | null;
	price_base_amount_rub?: number | null;
	price_base_amount_kgs?: number | null;
};

type Currency = "USD" | "RUB" | "KGS";

// localStorage currency
function getPreferredCurrency(): Currency {
	if (typeof window === "undefined") return "USD";
	const v = window.localStorage.getItem("APP_CURRENCY");
	if (v === "RUB" || v === "KGS" || v === "USD") return v;
	return "USD";
}

// number formatting per currency
function formatMoney(amount: number | string | null | undefined, currency: Currency, locale = "ru-RU") {
	if (amount == null) return "";
	const num = typeof amount === "string" ? parseFloat(amount) : amount;
	if (!isFinite(num)) return "";

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
	// KGS: символа нет в Intl — оформляем как у тебя визуально
	return `${Math.round(num).toLocaleString(locale)} с̲`;
}

// unlimited label
function limitLabel(value: number | null | undefined, unlimited: string) {
	if (value === null || value === 0) return unlimited;
	return String(value);
}

function CheckCircle() {
	return (
		<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
			<IoIosCheckmark />
		</i>
	);
}
function NoCheckCircle() {
	return (
		<i className="block w-fit bg-red-500 rounded-full text-black text-sm">
			<IoIosClose />
		</i>
	);
}

// derived prices from plan + currency
function pickPrices(plan: PlanDTO, currency: Currency) {
	// base amount
	const usdAmount = plan.price_amount ? parseFloat(plan.price_amount) : null;
	const usdBase = plan.price_base_amount ? parseFloat(plan.price_base_amount) : null;

	if (currency === "RUB") {
		return {
			amount: plan.price_amount_rub ?? (usdAmount != null ? usdAmount : null),
			base: plan.price_base_amount_rub ?? (usdBase != null ? usdBase : null),
		};
	}
	if (currency === "KGS") {
		return {
			amount: plan.price_amount_kgs ?? (usdAmount != null ? usdAmount : null),
			base: plan.price_base_amount_kgs ?? (usdBase != null ? usdBase : null),
		};
	}
	return { amount: usdAmount, base: usdBase };
}

// features list
function PlanFeatures({ plan, t }: { plan: PlanDTO; t: (k: string) => string }) {
	const unlimited = t("pricing.unlimited"); // ключ пришлёшь сам
	const rows: Array<{ ok: boolean; label: React.ReactNode }> = [];

	if (plan.llm_engine_id) {
		rows.push({
			ok: true,
			label: (
				<p>
					<span className="text-yellow-400 font-bold">{plan.llm_engine_id} </span>
					{t("pricing.features.open_ai_model")}
				</p>
			),
		});
	}

	rows.push({
		ok: true,
		label: (
			<p>
				<span className="text-yellow-400 font-bold">{limitLabel(plan.ai_templates_limit, unlimited)} </span>
				{t("pricing.features.ai_templates")}
			</p>
		),
	});

	rows.push({
		ok: true,
		label: (
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
		label: (
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

	for (const [ok, label] of toggles) {
		rows.push({ ok, label: <p>{label}</p> });
	}

	return (
		<ul className="flex flex-col gap-5 text-sm">
			{rows.map((row, idx) => (
				<li key={idx} className="flex gap-3 items-center">
					{row.ok ? <CheckCircle /> : <NoCheckCircle />}
					{row.label}
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
			<div className="flex gap-4 items-center justify-center">
				<h2 className="text-4xl font-bold text-center text-gray-400">{price}</h2>
				<span className="text-sm block px-2 py-1 bg-neutral-800 rounded line-through text-gray-400">
					{baseFmt}
				</span>
			</div>
		);
	}
	return <h2 className="text-4xl font-bold text-center text-gray-400">{price}</h2>;
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
		<div className="pricing-card min-w-[300px] max-w-[350px] bg-black rounded-3xl border border-gray-800 p-8 flex flex-col items-center gap-5 justify-between">
			<img src="/images/decorations/pricing-5-card-line.webp" alt="" className="pricing-card-line" />
			<div className="flex flex-col gap-5">
				<p className="text-center text-color-on-hover">{title}</p>
				{subtitle ? <p className="text-gray-400 text-center">{subtitle}</p> : null}

				<PlanPrice plan={plan} currency={currency} t={t} />
				<PlanFeatures plan={plan} t={t} />
			</div>

			<Button
				onClick={() => {}}
				className="mt-5 py-2 px-4 rounded-lg w-fit bg-indigo-500 hover:bg-indigo-600 duration-300"
			>
				{t("pricing.startofwork")}
			</Button>
		</div>
	);
}

function MonthlyTab({
	active,
	plans,
	t,
	currency,
}: {
	active: boolean;
	plans: PlanDTO[];
	t: (k: string) => string;
	currency: Currency;
}) {
	return (
		<div className={`pricing-tab flex gap-5 ${active ? "active" : ""}`}>
			{plans.map((p) => (
				<PlanCard
					key={p.id}
					plan={p}
					t={t}
					currency={currency}
					title={p.is_free ? t("pricing.vokalo_test") : t("pricing.monthly")}
					subtitle={p.is_free ? t("pricing.test_subtitle") : t("pricing.monthly_subtitle")}
				/>
			))}
		</div>
	);
}

function YearlyTab({
	active,
	plans,
	t,
	currency,
}: {
	active: boolean;
	plans: PlanDTO[];
	t: (k: string) => string;
	currency: Currency;
}) {
	return (
		<div className={`pricing-tab flex gap-5 ${active ? "active" : ""}`}>
			{plans.map((p) => (
				<PlanCard
					key={p.id}
					plan={p}
					t={t}
					currency={currency}
					title={t("pricing.yearly")}
					subtitle={t("pricing.getstarted")}
				/>
			))}
		</div>
	);
}

export default function PricingTab() {
	const [activeTab, setActiveTab] = useState(0);
	const { t, i18n } = useTranslation("common");
	const [monthlyPlans, setMonthlyPlans] = useState<PlanDTO[]>([]);
	const [yearlyPlans, setYearlyPlans] = useState<PlanDTO[]>([]);
	const [loading, setLoading] = useState(true);
	const [currency, setCurrency] = useState<Currency>("USD");

	useEffect(() => {
		setCurrency(getPreferredCurrency());
	}, []);

	useEffect(() => {
		const update = (e: Event) => {
			try {
				// @ts-ignore
				const code = e?.detail?.code as "USD" | "RUB" | "KGS" | undefined;
				if (code) setCurrency(code);
				else {
					const saved = window.localStorage.getItem("APP_CURRENCY") as any;
					if (saved === "USD" || saved === "RUB" || saved === "KGS") setCurrency(saved);
				}
			} catch {}
		};
		window.addEventListener("app:currency-changed", update as EventListener);
		return () => window.removeEventListener("app:currency-changed", update as EventListener);
	}, []);

	useEffect(() => {
		let mounted = true;
		async function load() {
			try {
				const [mResp, yResp] = await Promise.all([
					fetchData("plans/list/?period=monthly", "GET", undefined, false),
					fetchData("plans/list/?period=yearly", "GET", undefined, false),
				]);
				if (!mounted) return;
				const mData: PlanDTO[] = Array.isArray(mResp?.data) ? mResp.data : [];
				const yData: PlanDTO[] = Array.isArray(yResp?.data) ? yResp.data : [];
				setMonthlyPlans(mData);
				setYearlyPlans(yData);
			} catch (e) {
				console.error(e);
			} finally {
				if (mounted) setLoading(false);
			}
		}
		load();
		return () => {
			mounted = false;
		};
	}, []);

	return (
		<div className="flex flex-col gap-10 w-full">
			<div className="flex items-center gap-10 px-40 py-10">
				<p className="block border-b-1 flex-auto border-gray-800"></p>
				<div className="flex bg-neutral-900 rounded-xl border border-gray-700 px-8 py-4 gap-8">
					<Button
						className={`text-sm hover:text-indigo-500 duration-300 ${
							activeTab === 0 ? "text-indigo-500" : ""
						}`}
						onClick={() => setActiveTab(0)}
					>
						{t("pricing.monthly")}
					</Button>
					<Button
						className={`text-sm hover:text-indigo-500 duration-300 ${
							activeTab === 1 ? "text-indigo-500" : ""
						}`}
						onClick={() => setActiveTab(1)}
					>
						{t("pricing.yearly")}
					</Button>
				</div>
				<p className="block border-b-1 flex-auto border-gray-800"></p>
			</div>

			<div className="pricing-tabs px-40">
				{loading ? (
					<div className="text-center text-gray-400 py-10">{t("pricing.loading")}</div>
				) : (
					<>
						<MonthlyTab active={activeTab === 0} plans={monthlyPlans} t={t} currency={currency} />
						<YearlyTab active={activeTab === 1} plans={yearlyPlans} t={t} currency={currency} />
					</>
				)}
			</div>
		</div>
	);
}
