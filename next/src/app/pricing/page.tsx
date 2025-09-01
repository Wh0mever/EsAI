"use client";

import "@/assets/style.scss";
import PricingTab from "@/components/ui/tabs/PricingTab";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Link from "next/link";
import { useTranslation } from "react-i18next";

export default function Pricing() {
	const { t } = useTranslation("common");

	return (
		<main  className="pt-80 overflow-hidden relative">
			<Breadcrumb />

			<div className="flex flex-col items-center gap-3">
				<span className="px-3 py-2 bg-gray-900 rounded-lg text-sm">{t("pricing.subtitle")}</span>
				<h5 className="text-5xl">{t("pricing.title")}</h5>
				<PricingTab />
				<div className="px-40 py-10 flex flex-col items-start w-full gap-2">
					<h3>{t("pricing.questions")}</h3>
					<div className="flex gap-1">
						<p className="text-gray-400">{t("pricing.questionsText")}</p>
						<a
							href="mailto:support@esai.kg"
							className="text-indigo-400 hover:text-indigo-500 duration-300"
						>
							support@esai.kg
						</a>
					</div>

					<Link href="/faq" className="text-indigo-400 hover:text-indigo-500 duration-300">
						{t("pricing.questionsLink")}
					</Link>
				</div>
			</div>
		</main>
	);
}
