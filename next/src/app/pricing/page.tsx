"use client";

import "@/assets/style.scss";
import PricingTab from "@/components/ui/tabs/PricingTab";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Link from "next/link";
import { useTranslation } from "react-i18next";

export default function Pricing() {
	const { t } = useTranslation("common");

	return (
		<main className="pt-80 overflow-hidden relative">
			<Breadcrumb />

			<div className="flex flex-col items-center gap-3">
				<span className="px-3 py-2 bg-gray-900 rounded-lg text-sm">{t("pricing.subtitle")}</span>
				<h5 className="text-5xl">{t("pricing.title")}</h5>
				<PricingTab />

				{/* Referral program promo */}
				<div className="lg:px-40 px-6 w-full">
					<div className="mt-10 rounded-2xl border border-white/10 bg-neutral-900/60 backdrop-blur p-6 flex flex-col gap-3">
						<h3 className="text-2xl font-semibold">
							{t("pricing_referral.referral_title", { defaultValue: "Реферальная программа Vokalo" })}
						</h3>
						<p className="text-neutral-300">
							{t("pricing_referral.referral_subtitle", {
								defaultValue: "Расширьте ваши возможности с нашей реферальной программой.",
							})}
						</p>
						<p className="text-neutral-300">
							{t("pricing_referral.referral_line", { defaultValue: "Друг моего друга — мой друг 🙂" })}
						</p>
						<p className="text-neutral-300">
							{t("pricing_referral.referral_desc", {
								defaultValue:
									"Увеличивайте лимиты за каждого нового участника, зарегистрированного по вашему уникальному реферальному коду.",
							})}
						</p>
						<div>
							<Link
								href="/referral"
								className="inline-block mt-1 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white"
							>
								{t("pricing_referral.referral_more", { defaultValue: "Узнать подробнее" })}
							</Link>
						</div>
					</div>
				</div>
				<div className="lg:px-40 px-10 py-10 flex flex-col items-center w-full gap-2 z-10">
					<h3>{t("pricing.questions")}</h3>
					<div className="flex gap-1 text-center">
						<p className="text-gray-400">
							<span>{t("pricing.questionsText")}</span>
							<a
								href="mailto:support@esai.kg"
								className="text-indigo-400 hover:text-indigo-500 duration-300 ms-2"
							>
								support@esai.kg
							</a>
						</p>
					</div>

					<Link href="/faq" className="text-indigo-400 hover:text-indigo-500 duration-300 mt-3">
						{t("pricing.questionsLink")}
					</Link>
				</div>
			</div>
		</main>
	);
}
