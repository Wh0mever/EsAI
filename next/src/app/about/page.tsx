'use client';

import "@/assets/style.scss";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

/**
 * «О нас» — тёплый текст клиента (2026-07-03). Структура: благодарность →
 * зачем создали → что получаете (4 пункта) → «пишите нам» → добро пожаловать.
 * Цвета на токенах темы — страница читается и в светлой, и в тёмной теме.
 */
export default function About() {
	const { t } = useTranslation("common");
	const intro = t("about.intro", { returnObjects: true }) as string[];
	const features = t("about.features", { returnObjects: true }) as string[];
	const daily = t("about.daily", { returnObjects: true }) as string[];

	return (
		<main className="mx-auto pt-80 overflow-hidden relative">
			<Breadcrumb />

			<section className="py-10 max-w-3xl mx-auto px-4">
				<h1 className="text-3xl font-bold text-center mb-6">{t("about.title")}</h1>

				<p className="text-center text-xl text-foreground font-semibold my-8">
					{t("about.thanks")} <span aria-hidden>💛</span>
				</p>

				<div className="space-y-4 text-muted leading-relaxed">
					{Array.isArray(intro) && intro.map((p, i) => <p key={i}>{p}</p>)}
				</div>

				<h2 className="text-xl font-bold mt-10 mb-4">{t("about.features_title")}</h2>
				<ul className="space-y-3 text-foreground">
					{Array.isArray(features) && features.map((item, i) => (
						<li key={i} className="flex gap-2.5">
							<span className="text-accent shrink-0" aria-hidden>🔹</span>
							<span>{item}</span>
						</li>
					))}
				</ul>

				<hr className="my-10 border-border" />

				<div className="space-y-4 text-muted leading-relaxed">
					{Array.isArray(daily) && daily.map((p, i) => <p key={i}>{p}</p>)}
					<p className="text-center text-lg text-foreground font-medium py-2">
						{t("about.cta_quote")}
					</p>
					<p>{t("about.cta_after")}</p>
				</div>

				<p className="mt-10 text-center text-muted">
					{t("about.welcome")}
				</p>
			</section>
		</main>
	);
}
