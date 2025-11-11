"use client";

import React from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoExitOutline } from "react-icons/io5";
import Link from "next/link";
import { useTranslation } from "react-i18next";

type Props = {
	t: (k: string) => string;
	data: any;
	onUnsubscribe?: () => void;
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

export default function UserPlan({ t, data, onUnsubscribe }: Props) {
	const { i18n } = useTranslation();
	const lang = (i18n?.language || "ru").toLowerCase(); // "ru" | "en" | "kg/ky"
	const localeTag = mapLangToLocale(lang); // "ru-RU" | "en-US" | "ky-KG"

	const sub = data?.subscription;
	const hasSub = Boolean(sub && sub.plan);
	const currency = typeof window !== "undefined" ? localStorage.getItem("APP_CURRENCY") || "USD" : "USD";

	const CurrentPlan = () => {
		const plan = sub!.plan!;
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

				<div className="flex gap-2 mt-5">
					<Button
						className="px-6 py-2 rounded-xl bg-rose-500 hover:bg-rose-700 w-fit"
						onClick={onUnsubscribe}
						disabled={sub!.status !== "active"}
					>
						{t("profile.unsubscribe")}
					</Button>

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
		<div className="flex flex-col gap-3 w-full">
			<div className="flex justify-between items-center">
				<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
				<img src="/images/logo/head.svg" alt="" className="w-15" />
			</div>
			<div className="flex flex-col gap-3">
				<h3 className="text-3xl">{t("profile.plan_info.empty_title")}</h3>
				<p className="text-lg">{t("profile.plan_info.empty_text")}</p>
				<p className="text-md text-gray-400">{t("profile.plan_info.empty_text2")}</p>
				<Link href="/pricing" className="text-lg text-yellow-400 hover:text-yellow-500 duration-300">
					{t("profile.pricing")}
				</Link>
			</div>
		</div>
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
				<h2 className="text-xl font-bold">{t("profile.left_counters.title")}</h2>
                <div className="grid grid-cols-1 lg:grid-cols-2 md:grid-cols-2 gap-3">
                    {items.map((k) => (
                        <div key={k} className="rounded-xl border border-neutral-800 p-4 bg-white/5">
                            <div className="text-sm text-gray-400">{totals[k].label}</div>
                            <div className="mt-1 text-lg">
                                <strong className="text-white">{t("profile.left_counters.left")}:</strong>{" "}
                                {totals[k].unlimited ? "∞" : totals[k].total}
                            </div>
                            <div className="text-xs text-gray-400 mt-1">
                                план: {totals[k].left} • бонус: {totals[k].bonus}
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
			</>
		);
	}

	return (
		<Card>
			<EmptyPlan />
		</Card>
	);
}
