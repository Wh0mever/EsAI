'use client';

import "@/assets/style.scss";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

export default function About() {
	const { t } = useTranslation("common");
	const points = t("about.points", { returnObjects: true }) as string[];

	return (
		<main className="mx-auto pt-80 overflow-hidden relative">
			<Breadcrumb />

			<section className="py-10 max-w-4xl mx-auto px-4">
				<h1 className="text-3xl font-bold text-center mb-6">{t("about.title")}</h1>

				<p className="text-center text-gray-700 dark:text-gray-300 text-base my-10">
					{t("about.subtitle")}
				</p>

				<ul className="space-y-3 list-disc pl-6 text-gray-800 dark:text-gray-200">
					{points.map((item, index) => (
						<li key={index}>{item}</li>
					))}
				</ul>

				<p className="mt-10 text-center text-gray-600 dark:text-gray-400">
					{t("about.footer")}
				</p>
			</section>
		</main>
	);
}
