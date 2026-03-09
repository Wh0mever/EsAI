"use client";

import React from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoExitOutline } from "react-icons/io5";
import Link from "next/link";
import Image from "next/image";
import { useTranslation } from "react-i18next";
import { ConfirmationModal, Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";

type Props = {
	t: (k: string) => string;
	data: any;
	onUnsubscribe?: () => Promise<{ ok: boolean; error?: string }>;
	onResume?: () => Promise<{ ok: boolean; error?: string }>;
};

type CurrencyCode = "USD" | "RUB" | "KGS";

type UnitPricesData = {
	music_price: string | number;
	image_price: string | number;
	text_price: string | number;
	music_price_rub?: string | number | null;
	music_price_kgs?: string | number | null;
	image_price_rub?: string | number | null;
	image_price_kgs?: string | number | null;
	text_price_rub?: string | number | null;
	text_price_kgs?: string | number | null;
};

function mapLangToLocale(lang?: string) {
	switch ((lang || "ru").toLowerCase()) {
		case "en":
		case "en-us":
			return "en-US";
		case "kg":
		case "ky":
		case "ky-kg":
			return "ky-KG";
		case "ru":
		case "ru-ru":
		default:
			return "ru-RU";
	}
}

function formatDate(iso?: string | null, locale: string = "ru-RU") {
	if (!iso) return "—";
	const d = new Date(iso);
	if (isNaN(d.getTime())) return "—";
	return new Intl.DateTimeFormat(locale, {
		year: "numeric",
		month: "long",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
	}).format(d);
}

function localeTitle(locale: string | undefined, data: any) {
	if (locale === "ru") return data.template_name_ru;
	if (locale === "en") return data.template_name_en;
	if (locale === "kg" || locale === "ky") return data.template_name_kg;
	return data.template_name_en || data.template_name_ru || data.template_name_kg;
}

function formatPlanPeriod(plan: any, t: (k: string) => string) {
	return plan.is_free ? t("profile.plan_info.empty_title") : t(`profile.plan_period.${plan.period}`) || plan.period;
}

function formatMoney(currency: any, plan: any) {
	const pricing: any = { USD: plan.price_amount, RUB: plan.price_amount_rub, KGS: plan.price_amount_kgs };
	if (!currency) currency = "USD";
	return `${pricing[currency] ?? plan.price_amount} ${currency}`;
}

export default function UserPlan({ t, data, onUnsubscribe, onResume }: Props) {
	const { i18n } = useTranslation();
	const lang = (i18n?.language || "ru").toLowerCase(); // "ru" | "en" | "kg/ky"
	const localeTag = mapLangToLocale(lang); // "ru-RU" | "en-US" | "ky-KG"

	const sub = data?.subscription;
	const hasSub = Boolean(sub && sub.plan);
	const currency = typeof window !== "undefined" ? localStorage.getItem("APP_CURRENCY") || "USD" : "USD";
	const [confirmOpen, setConfirmOpen] = React.useState(false);
	const [isUnsubscribing, setIsUnsubscribing] = React.useState(false);
	const [actionNotice, setActionNotice] = React.useState<string | null>(null);
	const [actionError, setActionError] = React.useState<string | null>(null);
	const [purchaseModalOpen, setPurchaseModalOpen] = React.useState(false);
	const [paymentOptionsOpen, setPaymentOptionsOpen] = React.useState(false);
	const [cryptoHelpOpen, setCryptoHelpOpen] = React.useState(false);
	const [unitPrices, setUnitPrices] = React.useState<UnitPricesData | null>(null);
	const [isUnitPricesLoading, setIsUnitPricesLoading] = React.useState(false);
	const [isPurchaseProcessing, setIsPurchaseProcessing] = React.useState(false);
	const [purchaseError, setPurchaseError] = React.useState<string | null>(null);
	const [purchaseCounters, setPurchaseCounters] = React.useState({ music: 0, images: 0, texts: 0 });
	const PURCHASE_STEP = 10;
	const MIN_PURCHASE_UNITS = 10;

	const autoRenewEnabled = sub?.auto_renew !== false && data?.user?.auto_renew !== false;
	const canUnsubscribe = Boolean(sub?.status === "active" && autoRenewEnabled && onUnsubscribe);
	const canResume = Boolean(sub?.status === "active" && !autoRenewEnabled && onResume);

	React.useEffect(() => {
		if (!hasSub) return;
		let mounted = true;

		const loadUnitPrices = async () => {
			setIsUnitPricesLoading(true);
			try {
				const res = await fetchData<{ configured?: boolean; data?: UnitPricesData | null }>(
					"payments/topup/pricing/",
					"GET",
					undefined,
					true
				);
				if (!mounted) return;
				if (res.ok && res.data?.configured && res.data.data) {
					setUnitPrices(res.data.data);
				} else {
					setUnitPrices(null);
				}
			} finally {
				if (mounted) setIsUnitPricesLoading(false);
			}
		};

		loadUnitPrices();
		return () => {
			mounted = false;
		};
	}, [hasSub]);

	React.useEffect(() => {
		if (!purchaseModalOpen && !paymentOptionsOpen && !cryptoHelpOpen) {
			setPurchaseCounters({ music: 0, images: 0, texts: 0 });
			setPurchaseError(null);
		}
	}, [purchaseModalOpen, paymentOptionsOpen, cryptoHelpOpen]);

	const handleConfirmUnsubscribe = async () => {
		if (!onUnsubscribe) return;
		setIsUnsubscribing(true);
		setActionError(null);
		setActionNotice(null);
		try {
			const res = await onUnsubscribe();
			if (res?.ok) {
				setActionNotice(t("profile.unsubscribe_notice"));
			} else {
				setActionError(res?.error || t("common.error"));
			}
		} finally {
			setIsUnsubscribing(false);
			setConfirmOpen(false);
		}
	};

	const handleResume = async () => {
		if (!onResume) return;
		setActionError(null);
		setActionNotice(null);
		const res = await onResume();
		if (res?.ok) {
			setActionNotice(t("profile.resume_notice"));
		} else {
			setActionError(res?.error || t("common.error"));
		}
	};

	const safeCurrency: CurrencyCode = currency === "RUB" || currency === "KGS" ? currency : "USD";
	const fmt = new Intl.NumberFormat(localeTag, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
	const toNum = (v: string | number | null | undefined) => {
		const n = Number(v);
		return Number.isFinite(n) ? n : 0;
	};
	const money = (amount: number) => `${fmt.format(amount)} ${safeCurrency}`;
	const unitPriceByCurrency = {
		music: safeCurrency === "RUB" ? toNum(unitPrices?.music_price_rub) : safeCurrency === "KGS" ? toNum(unitPrices?.music_price_kgs) : toNum(unitPrices?.music_price),
		images: safeCurrency === "RUB" ? toNum(unitPrices?.image_price_rub) : safeCurrency === "KGS" ? toNum(unitPrices?.image_price_kgs) : toNum(unitPrices?.image_price),
		texts: safeCurrency === "RUB" ? toNum(unitPrices?.text_price_rub) : safeCurrency === "KGS" ? toNum(unitPrices?.text_price_kgs) : toNum(unitPrices?.text_price),
	};

	const purchaseRows = [
		{ key: "music", label: t("profile.buy_generations.items.music"), unitPrice: unitPriceByCurrency.music },
		{ key: "images", label: t("profile.buy_generations.items.images"), unitPrice: unitPriceByCurrency.images },
		{ key: "texts", label: t("profile.buy_generations.items.texts"), unitPrice: unitPriceByCurrency.texts },
	] as const;

	const totalSelected = purchaseCounters.music + purchaseCounters.images + purchaseCounters.texts;
	const totalAmount = purchaseRows.reduce(
		(sum, row) => sum + purchaseCounters[row.key] * row.unitPrice,
		0
	);

	const changeCounter = (kind: "music" | "images" | "texts", delta: number) => {
		setPurchaseCounters((prev) => ({
			...prev,
			[kind]: (() => {
				const current = prev[kind] || 0;
				if (delta > 0) {
					return current > 0 ? current + PURCHASE_STEP : MIN_PURCHASE_UNITS;
				}
				if (delta < 0) {
					return current > MIN_PURCHASE_UNITS ? current - PURCHASE_STEP : 0;
				}
				return current;
			})(),
		}));
	};

	const openPaymentOptions = () => {
		if (totalSelected <= 0) return;
		setPurchaseError(null);
		setPurchaseModalOpen(false);
		setPaymentOptionsOpen(true);
	};

	const onTopupPaymentStart = async () => {
		if (totalSelected <= 0) return;
		setIsPurchaseProcessing(true);
		setPurchaseError(null);
		try {
			const payload = {
				music: purchaseCounters.music,
				images: purchaseCounters.images,
				texts: purchaseCounters.texts,
			};
			const res = await fetchData("payments/topup/start/", "POST", payload, true);
			const redirectUrl = (res?.data as any)?.redirect_url;
			if (res.ok && typeof redirectUrl === "string" && redirectUrl.length > 0) {
				setPaymentOptionsOpen(false);
				window.location.href = redirectUrl;
				return;
			}
			setPurchaseError(res?.error || t("subscribe.error_unknown"));
		} catch {
			setPurchaseError(t("subscribe.error_unknown"));
		} finally {
			setIsPurchaseProcessing(false);
		}
	};

	const onCardBindStart = async () => {
		setIsPurchaseProcessing(true);
		setPurchaseError(null);
		try {
			const res = await fetchData("payments/card/bind/start/", "POST", { back_path: "/profile" }, true);
			const redirectUrl = (res?.data as any)?.redirect_url;
			if (res.ok && typeof redirectUrl === "string" && redirectUrl.length > 0) {
				window.location.href = redirectUrl;
				return;
			}
			setPurchaseError(res?.error || t("subscribe.error_unknown"));
		} catch {
			setPurchaseError(t("subscribe.error_unknown"));
		} finally {
			setIsPurchaseProcessing(false);
		}
	};

	const onCryptoPaymentOpen = () => {
		setPaymentOptionsOpen(false);
		setCryptoHelpOpen(true);
	};

	const CurrentPlan = () => {
		const plan = sub!.plan!;
		const issue = String(sub?.billing_issue_code || "");
		const graceUntil = sub?.grace_until ? formatDate(sub.grace_until, localeTag) : "";
		const isGraceActive = sub?.status === "active" && sub?.payment_status === "unpaid" && Boolean(sub?.grace_until);
		const isBlocked = sub?.status !== "active";
		const accessNotice = (() => {
			if (isGraceActive) {
				if (issue === "card_missing") return { kind: "warning", text: t("profile.billing_grace_card_missing", { date: graceUntil }) };
				if (issue === "charge_failed") return { kind: "warning", text: t("profile.billing_grace_charge_failed", { date: graceUntil }) };
				return { kind: "warning", text: t("profile.billing_grace_generic", { date: graceUntil }) };
			}
			if (isBlocked) {
				if (issue === "card_missing") return { kind: "error", text: t("profile.chat_blocked_card_missing") };
				if (issue === "charge_failed") return { kind: "error", text: t("profile.chat_blocked_charge_failed") };
				return { kind: "error", text: t("profile.chat_blocked_no_active") };
			}
			return null;
		})();
		return (
			<div className="flex flex-col gap-3 w-full">
				<div className="flex justify-between items-center">
					<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
					<i className="text-7xl text-gray-500">
						<IoExitOutline />
					</i>
				</div>

				<p>
					<strong>{t("profile.plan")}:</strong> {plan.name || localeTitle(lang, plan)}
				</p>

				<p>
					<strong>{t("profile.price")}:</strong> {formatMoney(currency, plan)}
					{plan.period ? ` / ${formatPlanPeriod(plan, t)}` : ""}
				</p>

				<p>
					<strong>{t("profile.status")}:</strong> {sub!.status} •{" "}
					{t(`profile.payment_status.${sub!.payment_status}`) || sub!.payment_status}
				</p>

				<p>
					<strong>{t("profile.start_date")}:</strong> {formatDate(sub!.start_date, localeTag)}
				</p>


				<p>
					{(() => {
						const nextChargeIso = sub!.end_date || sub!.payment_date;
						return (
							<>
								<strong>{t("profile.write-off")}:</strong> {formatDate(nextChargeIso, localeTag)}
							</>
						);
					})()}
				</p>

				{accessNotice && (
					<p className={accessNotice.kind === "warning" ? "text-sm text-amber-400" : "text-sm text-rose-400"}>
						{accessNotice.text}
					</p>
				)}
				{actionNotice && <p className="text-sm text-green-400">{actionNotice}</p>}
				{actionError && <p className="text-sm text-rose-400">{actionError}</p>}

				<div className="flex gap-2 mt-5">
					{autoRenewEnabled ? (
						<Button
							className="px-6 py-2 rounded-xl bg-rose-500 hover:bg-rose-700 w-fit"
							onClick={() => setConfirmOpen(true)}
							disabled={!canUnsubscribe}
						>
							{t("profile.unsubscribe")}
						</Button>
					) : (
						<Button
							className="px-6 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-600 w-fit"
							onClick={handleResume}
							disabled={!canResume}
						>
							{t("profile.resume_subscription")}
						</Button>
					)}

					<Link
						href="/pricing"
						className="px-6 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 duration-300"
					>
						{t("profile.change_plan")}
					</Link>
				</div>
			</div>
		);
	};

	const EmptyPlan = () => (
		(() => {
			const user = data?.user || {};
			const hasAnyBonus =
				Number(user?.bonus_texts || 0) > 0 ||
				Number(user?.bonus_images || 0) > 0 ||
				Number(user?.bonus_songs || 0) > 0 ||
				Number(user?.bonus_music || 0) > 0;
			const joinedRaw = user?.date_joined ? new Date(user.date_joined) : null;
			const trialEnd = joinedRaw && !isNaN(joinedRaw.getTime())
				? new Date(joinedRaw.getTime() + 7 * 24 * 60 * 60 * 1000)
				: null;
			const inTrialWindow = Boolean(trialEnd && Date.now() < trialEnd.getTime());
			return (
				<div className="flex flex-col gap-3 w-full">
					<div className="flex justify-between items-center">
						<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
						<img src="/images/logo/head.svg" alt="" className="w-15" />
					</div>
					<div className="flex flex-col gap-3">
						<h3 className="text-3xl">{t("profile.plan_info.empty_title")}</h3>
						<p className="text-lg">{t("profile.plan_info.empty_text")}</p>
						<p className="text-md text-gray-400">{t("profile.plan_info.empty_text2")}</p>
						{hasAnyBonus && inTrialWindow ? (
							<p className="text-sm text-amber-400">{t("profile.test_mode_notice")}</p>
						) : hasAnyBonus ? (
							<p className="text-sm text-rose-400">{t("profile.test_mode_expired_notice")}</p>
						) : (
							<p className="text-sm text-rose-400">{t("profile.chat_blocked_no_active")}</p>
						)}
						<Link href="/pricing" className="text-lg text-yellow-400 hover:text-yellow-500 duration-300">
							{t("profile.pricing")}
						</Link>
					</div>
				</div>
			);
		})()
	);

    const UsageCard = () => {
        const usage = sub?.usage || {};
        const user = data?.user || {};
        const [copied, setCopied] = React.useState(false);

        // Compute real remaining using backend-computed totals; fall back to left+bonus
        const totals = {
            texts: {
                total: sub?.remaining_texts ?? ((usage.texts_left ?? 0) + (user.bonus_texts ?? 0)),
                unlimited: Boolean(sub?.is_texts_unlimited),
                left: usage.texts_left ?? 0,
                bonus: user.bonus_texts ?? 0,
                label: t("profile.left_counters.items.texts"),
            },
            images: {
                total: sub?.remaining_images ?? ((usage.images_left ?? 0) + (user.bonus_images ?? 0)),
                unlimited: Boolean(sub?.is_images_unlimited),
                left: usage.images_left ?? 0,
                bonus: user.bonus_images ?? 0,
                label: t("profile.left_counters.items.images"),
            },
            songs: {
                total: sub?.remaining_songs ?? ((usage.songs_left ?? 0) + (user.bonus_songs ?? 0)),
                unlimited: Boolean(sub?.is_songs_unlimited),
                left: usage.songs_left ?? 0,
                bonus: user.bonus_songs ?? 0,
                label: t("profile.left_counters.items.songs"),
            },
            music: {
                total: sub?.remaining_music ?? ((usage.music_left ?? 0) + (user.bonus_music ?? 0)),
                unlimited: Boolean(sub?.is_music_unlimited),
                left: usage.music_left ?? 0,
                bonus: user.bonus_music ?? 0,
                label: t("profile.left_counters.items.music"),
            },
        } as const;

        const items = ["texts", "images", "songs", "music"] as const;

		function copyCode() {
			if (!user?.referral_uid) return;
			navigator.clipboard.writeText(String(user.referral_uid)).then(() => {
				setCopied(true);
				setTimeout(() => setCopied(false), 1500);
			});
		}

		return (
			<div className="flex flex-col gap-4 w-full">
				<div className="flex items-center justify-between gap-3">
					<h2 className="text-xl font-bold">{t("profile.left_counters.title")}</h2>
					<Button
						className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-sm"
						onClick={() => setPurchaseModalOpen(true)}
					>
						{t("profile.buy_generations.open_button")}
					</Button>
				</div>
	                <div className="grid grid-cols-1 lg:grid-cols-2 md:grid-cols-2 gap-3">
	                    {items.map((k) => (
	                        <div key={k} className="rounded-xl border border-neutral-800 p-4 bg-white/5">
                            <div className="text-sm text-gray-400">{totals[k].label}</div>
                            <div className="mt-1 text-lg">
                                <strong className="text-white">{t("profile.left_counters.left")}:</strong>{" "}
                                {totals[k].unlimited ? "∞" : totals[k].total}
	                            </div>
	                            <div className="text-xs text-gray-400 mt-1">
	                                {t("profile.left_counters.plan_part")}: {totals[k].left} • {t("profile.left_counters.bonus_part")}: {totals[k].bonus}
	                            </div>
	                        </div>
	                    ))}
	                </div>

				<div className="mt-4">
					<h3 className="text-lg font-semibold mb-2">{t("profile.referral.title")}</h3>
					<div className="flex items-center gap-3 mt-3">
						<div className="px-3 py-2 rounded-lg bg-neutral-800 text-white text-sm">
							<strong>{t("profile.referral.uid")}:</strong> {user?.referral_uid || "—"}
						</div>
						<Button className="px-4 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700" onClick={copyCode}>
							{copied ? t("profile.referral.copied") : t("profile.referral.copy")}
						</Button>
					</div>
				</div>
			</div>
		);
	};

	if (hasSub) {
		return (
			<>
				<Card>
					<CurrentPlan />
				</Card>
					<Card>
						<UsageCard />
					</Card>
					<Modal
						open={purchaseModalOpen}
						onClose={() => setPurchaseModalOpen(false)}
						title={t("profile.buy_generations.title")}
						size="md"
					>
						<div className="flex flex-col gap-4">
							{isUnitPricesLoading ? (
								<p className="text-sm text-gray-400">{t("profile.buy_generations.loading")}</p>
							) : !unitPrices ? (
								<p className="text-sm text-gray-300">{t("profile.buy_generations.empty_state")}</p>
							) : (
								<>
									{purchaseRows.map((row) => (
										<div key={row.key} className="rounded-xl border border-neutral-800 bg-white/5 p-3">
											<div className="flex items-center justify-between gap-3">
												<div>
													<div className="font-medium text-white">{row.label}</div>
													<div className="text-xs text-gray-400">
														{t("profile.buy_generations.unit_price")}: {money(row.unitPrice)}
													</div>
												</div>
												<div className="flex items-center gap-2">
													<button
														type="button"
														className="w-8 h-8 rounded-lg bg-neutral-800 hover:bg-neutral-700"
														onClick={() => changeCounter(row.key, -PURCHASE_STEP)}
													>
														-
													</button>
													<div className="min-w-10 text-center font-semibold">{purchaseCounters[row.key]}</div>
													<button
														type="button"
														className="w-8 h-8 rounded-lg bg-neutral-800 hover:bg-neutral-700"
														onClick={() => changeCounter(row.key, PURCHASE_STEP)}
													>
														+
													</button>
												</div>
											</div>
											<div className="text-xs text-gray-400 mt-2">
												{t("profile.buy_generations.row_total")}: {money(purchaseCounters[row.key] * row.unitPrice)}
											</div>
										</div>
									))}
									<div className="rounded-xl border border-neutral-800 bg-neutral-900 p-3">
										<div className="flex justify-between text-sm text-gray-300">
											<span>{t("profile.buy_generations.selected")}:</span>
											<strong>{totalSelected}</strong>
										</div>
										<div className="flex justify-between text-lg mt-2">
											<span>{t("profile.buy_generations.total")}:</span>
											<strong>{money(totalAmount)}</strong>
										</div>
									</div>
									{purchaseError && (
										<p className="text-sm text-rose-400">{purchaseError}</p>
									)}
									<Button
										className="w-full px-4 py-3 rounded-xl bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60"
										onClick={openPaymentOptions}
										disabled={totalSelected <= 0}
									>
										{t("subscribe.wallets_button")}
									</Button>
								</>
							)}
						</div>
					</Modal>
					<Modal
						open={paymentOptionsOpen}
						onClose={() => setPaymentOptionsOpen(false)}
						size="md"
						title={t("subscribe.payment_modal_title")}
					>
						<div className="space-y-5">
							<div className="text-sm text-white/80 leading-6">
								{t("subscribe.payment_modal_description")}
							</div>

							<div className="rounded-xl border border-white/10 bg-neutral-800/60 p-4">
								<h3 className="text-base font-semibold">{t("subscribe.card_title")}</h3>
								<p className="text-sm text-white/70 mt-2">
									{t("subscribe.card_description")}
								</p>
								<button
									type="button"
									onClick={onCardBindStart}
									disabled={isPurchaseProcessing}
									className="mt-4 w-full inline-flex items-center justify-center px-4 py-3 rounded-xl bg-indigo-500 hover:bg-indigo-600 transition-colors disabled:opacity-70"
								>
									{isPurchaseProcessing ? t("common.processing") : t("subscribe.card_button")}
								</button>
							</div>

							<div className="rounded-xl border border-white/10 bg-neutral-800/60 p-4">
								<h3 className="text-base font-semibold">{t("subscribe.wallets_title")}</h3>
								<p className="text-sm text-white/70 mt-2">
									{t("subscribe.wallets_description")}
								</p>
								<button
									type="button"
									onClick={onTopupPaymentStart}
									disabled={isPurchaseProcessing || totalSelected <= 0}
									className="mt-4 w-full inline-flex items-center justify-center px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 transition-colors disabled:opacity-70"
								>
									{isPurchaseProcessing ? t("common.processing") : t("subscribe.wallets_button")}
								</button>
							</div>

							<div className="rounded-xl border border-white/10 bg-neutral-800/60 p-4">
								<h3 className="text-base font-semibold">{t("subscribe.crypto_title")}</h3>
								<p className="text-sm text-white/70 mt-2">
									{t("subscribe.crypto_description")}
								</p>
								<button
									type="button"
									onClick={onCryptoPaymentOpen}
									className="mt-4 w-full inline-flex items-center justify-center px-4 py-3 rounded-xl bg-emerald-700 hover:bg-emerald-800 transition-colors"
								>
									{t("subscribe.crypto_button")}
								</button>
							</div>

							{purchaseError && (
								<p className="text-sm text-rose-400">{purchaseError}</p>
							)}

							<div className="rounded-xl border border-white/10 bg-neutral-900/80 p-4 text-sm text-white/85">
								{t("subscribe.payment_optional_note")}
							</div>
						</div>
					</Modal>
					<Modal
						open={cryptoHelpOpen}
						onClose={() => setCryptoHelpOpen(false)}
						size="md"
						title={t("subscribe.crypto_modal_title")}
					>
						<div className="space-y-4">
							<p className="text-sm text-white/80 leading-6">
								{t("subscribe.crypto_modal_description")}
							</p>
							<div className="rounded-xl border border-white/10 bg-neutral-800/60 p-3">
								<Image
									src="/images/binance.jpg"
									alt="Binance QR"
									width={900}
									height={900}
									className="w-full h-auto rounded-lg"
									priority={false}
								/>
							</div>
							<p className="text-sm text-white/80 leading-6">
								{t("subscribe.crypto_receipt_text")}
							</p>
							<a
								href="mailto:support@esai.kg"
								className="inline-flex items-center justify-center px-4 py-2 rounded-xl border border-white/20 hover:border-white/40 transition-colors text-sm"
							>
								support@esai.kg
							</a>
						</div>
					</Modal>
					<ConfirmationModal
						isOpen={confirmOpen}
						title={t("profile.unsubscribe_confirm_title")}
					description={t("profile.unsubscribe_confirm_desc")}
					confirmText={t("common.yes")}
					confirmLoadingText={t("common.loading")}
					cancelText={t("common.no")}
					onConfirm={handleConfirmUnsubscribe}
					onCancel={() => setConfirmOpen(false)}
					confirmDisabled={isUnsubscribing}
				/>
			</>
		);
	}

	return (
		<Card>
			<EmptyPlan />
		</Card>
	);
}
