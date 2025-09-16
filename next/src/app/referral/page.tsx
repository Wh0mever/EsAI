"use client";

import "@/assets/style.scss";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

export default function Blog() {
	const { t } = useTranslation("common");

	return (
		<main  className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
			<Breadcrumb />

			<div className="mx-auto max-w-4xl px-4 py-5">
				<section className="py-10">
					<h1 className="text-3xl font-bold text-center">{t("referral.title")}</h1>
					<p className="text-center text-gray-700 dark:text-gray-300 text-base mt-5">{t("referral.subtitle")}</p>
				</section>

				<section className="py-5">
					<h2 className="text-2xl font-semibold text-center">{t("referral.how_title")}</h2>

					<div className="grid md:grid-cols-3 grid-cols-1 gap-6 mt-5">
						<div className="rounded-xl border border-neutral-200/50 dark:border-neutral-800 p-5 bg-white/60 dark:bg-neutral-900/50">
							<h3 className="font-semibold text-lg mb-2">{t("referral.step1.title")}</h3>
							<p className="text-sm text-neutral-600 dark:text-neutral-300">{t("referral.step1.text")}</p>
						</div>
						<div className="rounded-xl border border-neutral-200/50 dark:border-neutral-800 p-5 bg-white/60 dark:bg-neutral-900/50">
							<h3 className="font-semibold text-lg mb-2">{t("referral.step2.title")}</h3>
							<p className="text-sm text-neutral-600 dark:text-neutral-300">{t("referral.step2.text")}</p>
						</div>
						<div className="rounded-xl border border-neutral-200/50 dark:border-neutral-800 p-5 bg-white/60 dark:bg-neutral-900/50">
							<h3 className="font-semibold text-lg mb-2">{t("referral.step3.title")}</h3>
							<p className="text-sm text-neutral-600 dark:text-neutral-300">{t("referral.step3.text")}</p>
						</div>
					</div>
				</section>

				<section className="py-5">
					<h2 className="text-2xl font-semibold mb-4 text-center">{t("referral.usage_title")}</h2>
					<ul className="list-disc pl-6 space-y-2 text-neutral-700 dark:text-neutral-300 py-3">
						<li>{t("referral.usage1")}</li>
						<li>{t("referral.usage2")}</li>
						<li>{t("referral.usage3")}</li>
					</ul>
				</section>
			</div>
		</main>
	);
}
