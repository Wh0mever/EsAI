"use client";

import "@/assets/style.scss";
import PricingTab from "@/components/ui/tabs/PricingTab";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Questions from "@/components/global/Questions";
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
				<Questions />
			</div>
		</main>
	);
}
