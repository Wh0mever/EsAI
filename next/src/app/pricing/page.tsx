"use client";

import "@/assets/style.scss";
import TokenPackages from "@/components/pricing/TokenPackages";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Link from "next/link";
import { useTranslation } from "react-i18next";

export default function Pricing() {
	const { t } = useTranslation("common");

	return (
		<main className="pt-80 overflow-hidden relative">
			<Breadcrumb />

			<div className="flex flex-col items-center gap-3">
				<span className="px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-muted">
					{t("packages.subtitle", { defaultValue: "EsAI | Оплата по факту использования" })}
				</span>
				<h5 className="text-5xl text-center">
					{t("packages.title", { defaultValue: "Пополнение баланса" })}
				</h5>
				<p className="text-muted text-center max-w-xl px-4">
					{t("packages.lead", {
						defaultValue:
							"Платите только за то, что используете. Выберите пакет токенов и пополните баланс — без подписок.",
					})}
				</p>

				<TokenPackages />

				{/* Referral program promo */}
				<div className="lg:px-40 px-6 w-full">
					<div className="mt-4 rounded-2xl border border-border bg-surface-2 p-6 flex flex-col gap-3">
						<h3 className="text-2xl font-semibold text-foreground">
							{t("pricing_referral.referral_title", { defaultValue: "Реферальная программа EsAI" })}
						</h3>
						<p className="text-muted">
							{t("pricing_referral.referral_subtitle", {
								defaultValue: "Расширьте ваши возможности с нашей реферальной программой.",
							})}
						</p>
						<p className="text-muted">
							{t("pricing_referral.referral_desc", {
								defaultValue:
									"Получайте бонусные токены за каждого нового участника, зарегистрированного по вашему реферальному коду.",
							})}
						</p>
						<div>
							<Link
								href="/referral"
								className="inline-block mt-1 px-4 py-2 rounded-lg bg-accent text-on-accent font-semibold hover:bg-accent-strong transition-colors"
							>
								{t("pricing_referral.referral_more", { defaultValue: "Узнать подробнее" })}
							</Link>
						</div>
					</div>
				</div>

				<div className="lg:px-40 px-10 py-10 flex flex-col items-center w-full gap-2 z-10">
					<h3 className="text-foreground">{t("packages.questions", { defaultValue: "Остались вопросы?" })}</h3>
					<Link href="/faq" className="text-accent-strong hover:text-accent duration-300 mt-3">
						{t("packages.questions_link", { defaultValue: "Перейти в FAQ" })}
					</Link>
				</div>
			</div>
		</main>
	);
}
