"use client";

import "@/assets/style.scss";
import NoData from "@/components/NoData/NoData";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/PageView/Breadcrumb";

export default function Blog() {
	const { t } = useTranslation("common");
	const points = t("blog.points", { returnObjects: true }) as string[];

	return (
		<main className="mx-auto pt-80 overflow-hidden relative px-4">
			<Breadcrumb />

			<div className="mx-auto max-w-4xl px-4 py-4">
				<section className="py-10">
					<h1 className="text-3xl font-bold text-center">{t("blog.title")}</h1>
					<p className="text-center text-gray-700 dark:text-gray-300 text-base my-10">{t("blog.subtitle")}</p>

					<ul className="space-y-3 list-disc pl-6 text-gray-800 dark:text-gray-200">
						{points.map((item, index) => (
							<li key={index}>{item}</li>
						))}
					</ul>

					<p className="mt-10 text-center text-gray-600 dark:text-gray-400">{t("blog.footer")}</p>
				</section>

				<section className="py-12">
					<NoData />
				</section>
			</div>
		</main>
	);
}
