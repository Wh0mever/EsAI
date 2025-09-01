'use client';

import PricingTab from "@/components/ui/tabs/PricingTab";
import { useTranslation } from "react-i18next";

export default function Pricing() {

	const { t } = useTranslation('common');

	return (
		<section className="flex flex-col py-20 gap-10 relative section-divider">
			<div className="absolute w-full h-full top-0 left-0 z-[-1]">
				<img
					src="/images/decorations/pricing-section-5-shape-top.webp"
					className="absolute top-0 left-1/2 transform -translate-x-1/2"
					alt=""
				/>
				<img
					src="/images/decorations/pricing-section-5-shape-left.webp"
					className="absolute top-0 left-0"
					alt=""
				/>
				<img
					src="/images/decorations/pricing-section-5-shape-right.webp"
					className="absolute top-0 right-0"
					alt=""
				/>
			</div>

			<div className="w-full flex justify-center items-center flex-col gap-5">
				<div className="px-6 py-2 bg-indigo-600/20 rounded-lg w-fit">
					<span>{t('pricing.title')}</span>
				</div>

				<h2 className="text-5xl text-center">{t('pricing.subtitle')}</h2>
			</div>
			<PricingTab />
		</section>
	);
}
