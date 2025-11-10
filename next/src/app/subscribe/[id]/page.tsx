"use client";

import "@/assets/style.scss";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { fetchData } from "@/tools/fetchData";
import Cookies from "js-cookie";
import { getInitialCurrency } from "@/lib/currency";
import { Alert } from "@/components/ui/alert/Alert";

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

	template_name_ru?: string | null;
	template_name_en?: string | null;
	template_name_kg?: string | null;
};

type Currency = "USD" | "RUB" | "KGS";

// ==== Utils ====
function getPreferredCurrency(): Currency { return getInitialCurrency(); }

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

function pickPrices(plan: PlanDTO, currency: Currency) {
	const usdAmount = plan.price_amount ? parseFloat(plan.price_amount) : null;
	const usdBase = plan.price_base_amount ? parseFloat(plan.price_base_amount) : null;

	if (currency === "RUB")
		return { amount: plan.price_amount_rub ?? usdAmount, base: plan.price_base_amount_rub ?? usdBase };
	if (currency === "KGS")
		return { amount: plan.price_amount_kgs ?? usdAmount, base: plan.price_base_amount_kgs ?? usdBase };
	return { amount: usdAmount, base: usdBase };
}

function limitLabel(value: number | null | undefined, unlimited: string) {
	if (value === null || value === 0) return unlimited;
	return String(value);
}

function selectPlanTitle(plan: PlanDTO, lang: "ru" | "en" | "kg") {
	const map: Record<string, string | null | undefined> = {
		ru: plan.template_name_ru,
		en: plan.template_name_en,
		kg: plan.template_name_kg,
	};
	return (map[lang] || plan.template_name_ru || plan.template_name_en || plan.template_name_kg || "")?.trim();
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

function PriceBlock({ plan, currency, t }: { plan: PlanDTO; currency: Currency; t: (k: string) => string }) {
	const { amount, base } = pickPrices(plan, currency);
	const price = formatMoney(amount, currency);
	const baseFmt = base != null ? formatMoney(base, currency) : null;

	if (plan.is_free) {
		return <div className="text-5xl font-bold">{t("pricing.free")}</div>;
	}

	return (
		<div className="flex items-baseline gap-4">
			<div className="text-5xl font-bold">{price}</div>
			{baseFmt && <div className="text-sm line-through text-gray-500">{baseFmt}</div>}
			<div className="text-sm text-gray-400">/ {t(`pricing.${plan.period}_short`)}</div>
		</div>
	);
}

// ==== Page ====
export default function SubscribePlanPage() {
	const { t, i18n } = useTranslation("common");
	const params = useParams<{ id: string }>();
	const [plan, setPlan] = useState<PlanDTO | null>(null);
	const [loading, setLoading] = useState(true);
	const [currency, setCurrency] = useState<Currency>(() => (typeof window !== "undefined" ? getInitialCurrency() : "USD"));
    const [authed, setAuthed] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [activeForMe, setActiveForMe] = useState(false);
    const [nextChargeAt, setNextChargeAt] = useState<string | null>(null);
    const [redirectCounter, setRedirectCounter] = useState<number | null>(null);
    const router = useRouter();
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [showAlert, setShowAlert] = useState(false);
    const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");
    const [alertTitle, setAlertTitle] = useState<string>("");
    const [alertMessage, setAlertMessage] = useState<string>("");

	const lang = useMemo<"ru" | "en" | "kg">(
		() => (i18n.language ?? "ru").split("-")[0] as "ru" | "en" | "kg",
		[i18n.language]
	);

	useEffect(() => {
		setCurrency(getPreferredCurrency());
		setAuthed(Boolean(Cookies.get("access")));
		const onCurrency = (e: Event) => {
			try {
				// @ts-ignore
				const code = e?.detail?.code as Currency | undefined;
				if (code) setCurrency(code);
			} catch {}
		};
		window.addEventListener("app:currency-changed", onCurrency as EventListener);
		return () => window.removeEventListener("app:currency-changed", onCurrency as EventListener);
    }, []);

	useEffect(() => {
		let mounted = true;
		(async () => {
			try {
				const targetId = Number(params.id);
				const [mResp, yResp] = await Promise.all([
					fetchData("plans/list/?period=monthly", "GET", undefined, false),
					fetchData("plans/list/?period=yearly", "GET", undefined, false),
				]);
				const listM: PlanDTO[] = Array.isArray(mResp?.data) ? mResp.data : [];
				const listY: PlanDTO[] = Array.isArray(yResp?.data) ? yResp.data : [];
				const found = [...listM, ...listY].find((p) => Number(p.id) === targetId) || null;

				if (!mounted) return;
				setPlan(found);
			} catch (e) {
				console.error("Failed to load plan", e);
				setPlan(null);
			} finally {
				mounted && setLoading(false);
			}
		})();
		return () => {
			mounted = false;
		};
	}, [params.id]);

    // Load my active subscription to decide UI state for this plan
    useEffect(() => {
        let abort = false;
        (async () => {
            if (!authed || !plan) {
                setActiveForMe(false);
                setNextChargeAt(null);
                return;
            }
            const me = await fetchData("plans/me/subscription/", "GET", undefined, true);
            const sub: any = me?.data || null;
            const same = sub && sub.plan && Number(sub.plan.id) === Number(plan.id);
            if (abort) return;
            setActiveForMe(Boolean(same));
            setNextChargeAt(same ? (sub.end_date as string) : null);
        })();
        return () => { abort = true; };
    }, [authed, plan]);

    function formatDate(dateString: string | null): string {
        if (!dateString) return "";
        try {
            const d = new Date(dateString);
            const locale = (i18n.language || "ru").startsWith("en") ? "en-US" : (i18n.language.startsWith("kg") ? "ky-KG" : "ru-RU");
            return d.toLocaleDateString(locale, { year: "numeric", month: "long", day: "numeric" });
        } catch {
            return dateString;
        }
    }

	const title = useMemo(() => {
		if (!plan) return "";
		const local = selectPlanTitle(plan, lang);
		if (local) return local;
		return plan.is_free ? t("pricing.vokalo_test") : t(`pricing.${plan.period}`);
	}, [plan, lang, t]);

	const subtitle = useMemo(() => {
		if (!plan) return "";
		return plan.is_free ? t("pricing.test_subtitle") : t(`pricing.${plan.period}_subtitle`);
    }, [plan, t]);

    async function handleConnectPlanClick() {
        if (!authed) return;
        setActionLoading(true);
        try {
            if (!plan) {
                setAlertType("error");
                setAlertTitle(t("subscribe.error_plan_not_found"));
                setAlertMessage("");
                setShowAlert(true);
                return;
            }
            const res = await fetchData(`plans/activate/${plan.id}/`, "POST", {}, true);
            if (res.ok) {
                setAlertType("success");
                setAlertTitle(t("subscribe.success_title"));
                // For paid plans: start 10s redirect countdown to profile
                if (!plan.is_free) {
                    setRedirectCounter(10);
                    setAlertMessage(
                        `${t("subscribe.success_message")} ${t("subscribe.redirect_in_profile", { seconds: 10 })}`
                    );
                    setShowAlert(true);
                } else {
                    setAlertMessage(t("subscribe.success_message"));
                    setShowAlert(true);
                }
                return;
            }
            const code = (res.data as any)?.message || res.error || "unknown";
            if (code === "already_active") {
                setAlertType("error");
                setAlertTitle(t("subscribe.error_already_active"));
                setAlertMessage("");
                setShowAlert(true);
            } else if (code === "plan_not_found") {
                setAlertType("error");
                setAlertTitle(t("subscribe.error_plan_not_found"));
                setAlertMessage("");
                setShowAlert(true);
            } else if (code === "no_card") {
                setAlertType("error");
                setAlertTitle(t("subscribe.attach_card_title"));
                setAlertMessage(t("subscribe.no_card_short"));
                setShowAlert(true);
            } else if (code === "no_token") {
                setAlertType("error");
                setAlertTitle(t("subscribe.attach_card_title"));
                setAlertMessage(t("subscribe.error_no_token"));
                setShowAlert(true);
            } else {
                setAlertType("error");
                setAlertTitle(t("subscribe.error_unknown"));
                setAlertMessage("");
                setShowAlert(true);
            }
        } catch (e) {
            setAlertType("error");
            setAlertTitle(t("subscribe.error_unknown"));
            setAlertMessage("");
            setShowAlert(true);
        } finally {
            setActionLoading(false);
        }
    }

    function onActivateClick() {
        // Open confirmation modal instead of immediate activation
        setConfirmOpen(true);
    }

    async function onConfirmActivate() {
        setConfirmOpen(false);
        await handleConnectPlanClick();
    }

    // Countdown redirect effect
    useEffect(() => {
        if (redirectCounter === null) return;
        if (redirectCounter <= 0) {
            setShowAlert(false);
            router.push("/profile");
            return;
        }
        const id = window.setTimeout(() => setRedirectCounter((s) => (s ? s - 1 : 0)), 1000);
        return () => window.clearTimeout(id);
    }, [redirectCounter, router]);

	return (
		<main className="pt-56 sm:pt-64 overflow-hidden relative">
			<div className="absolute  top-0 -z-10">
				<Breadcrumb />
			</div>

			<section className="px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 z-100">
				<div className="mb-6">
					<Link href="/pricing" className="text-indigo-400 hover:text-indigo-500 duration-300">
						← {t("pricing.back_to_all")}
					</Link>
				</div>

				{loading && <div className="text-center text-gray-400 py-16">{t("pricing.loading")}</div>}

				{!loading && !plan && (
					<div className="text-center text-gray-400 py-16">
						{t("pricing.not_found")}
						<div className="mt-3">
							<Link href="/pricing" className="text-indigo-400 hover:text-indigo-500 duration-300">
								{t("pricing.back_to_all")}
							</Link>
						</div>
					</div>
				)}

				{!loading && plan && (
					<>
						{/* Hero */}
						<div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-neutral-900 to-black border border-white/10 p-8 md:p-12">
							<div className="flex flex-col gap-4">
								<span className="inline-flex w-fit items-center gap-2 text-xs px-3 py-1 rounded-full bg-white/5 border border-white/10 text-white/70">
									{t("pricing.plan")} • {t(`pricing.${plan.period}`)}
								</span>
								<h1 className="text-4xl md:text-5xl font-semibold tracking-tight">{title}</h1>
								{subtitle && <p className="text-white/70 max-w-2xl">{subtitle}</p>}
								<div className="pt-2">
									<PriceBlock plan={plan} currency={currency} t={t} />
								</div>
							</div>
						</div>

						{/* Details */}
						<section className="mt-10 grid grid-cols-1 lg:grid-cols-3 gap-8">
							<div className="lg:col-span-2">
								<h2 className="text-xl font-semibold pb-5">{t("pricing.included")}</h2>
								<ul className="grid grid-cols-1 sm:grid-cols-2 gap-4">
									{plan.llm_engine_id ? (
										<li className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10">
											<Check />
											<p>
												<span className="text-yellow-400 font-bold">{plan.llm_engine_id} </span>
												{t("pricing.features.open_ai_model")}
											</p>
										</li>
									) : (
										<li className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10">
											<Cross />
											<p>{t("pricing.features.open_ai_model")}</p>
										</li>
									)}

									<li className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10">
										<Check />
										<p>
											<span className="text-yellow-400 font-bold">
												{limitLabel(plan.ai_templates_limit, t("pricing.unlimited"))}{" "}
											</span>
											{t("pricing.features.ai_templates")}
										</p>
									</li>

									<li className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10">
										<Check />
										<p>
											<span className="text-yellow-400 font-bold">
												{limitLabel(plan.operations_per_month_limit, t("pricing.unlimited"))}{" "}
											</span>
											{t("pricing.features.ops_per_month")}
										</p>
									</li>

									<li className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10">
										<Check />
										<p>
											<span className="text-yellow-400 font-bold">
												{limitLabel(plan.covers_limit, t("pricing.unlimited"))}{" "}
											</span>
											{t("pricing.features.covers")}
										</p>
									</li>

									{(
										[
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
										] as Array<[boolean, string]>
									).map(([ok, label], i) => (
										<li
											key={i}
											className="flex items-start gap-3 p-4 rounded-xl bg-neutral-900/60 border border-white/10"
										>
											{ok ? <Check /> : <Cross />}
											<p>{label}</p>
										</li>
									))}
								</ul>
							</div>

							<aside className="lg:col-span-1">
								<div className="rounded-2xl border border-white/10 bg-neutral-900/40 p-6 sticky top-24">
									<h3 className="text-lg font-semibold mb-2">{t("pricing.meta")}</h3>
									<dl className="space-y-3 text-sm">
										<div className="flex justify-between border-b border-white/10 pb-2">
											<dt className="text-white/60">{t("pricing.period")}</dt>
											<dd>{t(`pricing.${plan.period}`)}</dd>
										</div>
										<div className="flex justify-between border-b border-white/10 pb-2">
											<dt className="text-white/60">{t("pricing.duration_days")}</dt>
											<dd>{plan.duration_days}</dd>
										</div>
										<div className="flex justify-between">
											<dt className="text-white/60">{t("pricing.addons")}</dt>
											<dd>{plan.can_purchase_addons ? t("common.yes") : t("common.no")}</dd>
										</div>
									</dl>
								</div>
							</aside>
						</section>

						{/* Bottom CTA */}
						<div className="mt-12 pb-10 border-t border-white/10 pt-6 flex flex-col items-center gap-3">
                        {authed ? (
                            activeForMe ? (
                                <div className="text-center">
                                    <div className="text-green-400 font-medium">{t("pricing.plan_already_active")}</div>
                                    {nextChargeAt && (
                                        <div className="text-white/70 mt-1">{t("pricing.next_charge_on", { date: formatDate(nextChargeAt) })}</div>
                                    )}
                                </div>
                            ) : (
                                <button
                                    type="button"
                                    onClick={onActivateClick}
                                    disabled={actionLoading}
                                    className="inline-flex items-center justify-center px-6 py-3 rounded-xl bg-indigo-500 hover:bg-indigo-600 transition-colors disabled:opacity-70"
                                >
                                    {actionLoading ? t("common.processing") : t("pricing.connect_plan")}
                                </button>
                            )
                        ) : (
                            <div className="flex flex-col sm:flex-row items-center gap-3">
                                <Link
                                    href="/auth/signin"
                                    className="inline-flex items-center justify-center px-6 py-3 rounded-xl bg-indigo-500 hover:bg-indigo-600 transition-colors"
                                >
                                    {t("pricing.startofwork")}
                                </Link>
                            </div>
                        )}
                        <Link href="/pricing" className="text-indigo-400 hover:text-indigo-500 mt-5">
                            {t("pricing.view_all_plans")}
                        </Link>
                    </div>
                </>
            )}
        </section>
        {/* Inline alert portal trigger */}
        <Alert
            show={showAlert}
            onClose={() => setShowAlert(false)}
            type={alertType}
            title={alertTitle}
            message={alertMessage}
            position="top"
            autoClose={redirectCounter == null}
            autoCloseDuration={3500}
            actionHref={redirectCounter != null ? "/profile" : (alertType === "error" ? "/profile" : undefined)}
            actionText={redirectCounter != null ? t("subscribe.go_now") : (alertType === "error" ? t("subscribe.go_to_profile") : undefined)}
        />

        {/* Confirm activation modal */}
        <ConfirmationModal
            isOpen={confirmOpen}
            title={t("pricing.confirm_title")}
            description={t("pricing.confirm_description")}
            confirmText={t("common.yes")}
            cancelText={t("common.no")}
            confirmDisabled={actionLoading}
            confirmLoadingText={t("common.processing")}
            onConfirm={onConfirmActivate}
            onCancel={() => setConfirmOpen(false)}
        />
        </main>
    );
}
