"use client";

import "@/assets/style.scss";
import { useMemo, useState } from "react";
import TokenPackages from "@/components/pricing/TokenPackages";
import WhatsEnoughCalculator from "@/components/pricing/WhatsEnoughCalculator";
import CollapsibleCreditsExplainer from "@/components/pricing/CollapsibleCreditsExplainer";
import ExitDiscountPopup from "@/components/pricing/ExitDiscountPopup";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useExitDiscount } from "@/hooks/useExitDiscount";

function formatMMSS(totalSeconds: number): string {
	const s = Math.max(0, totalSeconds);
	const mm = Math.floor(s / 60);
	const ss = s % 60;
	return `${mm.toString().padStart(2, "0")}:${ss.toString().padStart(2, "0")}`;
}

export default function Pricing() {
	const { t } = useTranslation("common");
	const [paymentInProgress, setPaymentInProgress] = useState(false);
	const [claiming, setClaiming] = useState(false);
	const { active, showPopup, popupOffer, deviceKey, claim, dismiss, secondsLeft } =
		useExitDiscount(paymentInProgress);

	const popupMinutesLeft = useMemo(() => {
		if (!popupOffer?.expires_at) return null;
		// Math.round (не ceil): при show() сервер ставит РОВНО EXIT_DISCOUNT_MINUTES,
		// но сетевая задержка между ответом и этим рендером на пару сотен мс —
		// ceil() на 900001мс уже даёт 16 вместо честных 15. round не поддаётся
		// такой погрешности (это только текст в попапе; реальный отсчёт и гейт
		// оплаты по-прежнему считаются в секундах из expires_at на сервере).
		return Math.max(0, Math.round((new Date(popupOffer.expires_at).getTime() - Date.now()) / 60000));
	}, [popupOffer]);

	const handleClaim = async () => {
		if (claiming) return;
		setClaiming(true);
		try {
			await claim();
		} finally {
			setClaiming(false);
		}
	};

	return (
		<main className="pt-80 overflow-hidden relative">
			<Breadcrumb />

			{active && secondsLeft > 0 && (
				<div className="sticky top-0 z-50 w-full bg-accent text-on-accent text-center text-sm font-semibold py-2 px-4">
					{t("exitDiscount.banner", {
						defaultValue: "Скидка {{percent}}% действует ещё {{time}}",
						percent: active.percent,
						time: formatMMSS(secondsLeft),
					})}
				</div>
			)}

			<ExitDiscountPopup
				open={showPopup}
				percent={popupOffer?.percent ?? null}
				minutesLeft={popupMinutesLeft}
				claiming={claiming}
				onClaim={handleClaim}
				onDecline={dismiss}
			/>

			<div className="flex flex-col items-center gap-3">
				<span className="px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-muted">
					{t("packages.subtitle", { defaultValue: "EsAI | Оплата по факту использования" })}
				</span>
				<h1 className="text-3xl sm:text-4xl font-bold text-center">
					{t("packages.title", {
						defaultValue: "Тарифы EsAI — оплата в сомах, без подписок",
					})}
				</h1>
				<p className="text-muted text-center max-w-xl px-4">
					{t("packages.lead", {
						defaultValue:
							"Платите только за то, что используете. Выберите пакет кредитов и пополните баланс — без подписок.",
					})}
				</p>

				<TokenPackages
					discountPercent={active && secondsLeft > 0 ? active.percent : null}
					deviceKey={deviceKey}
					onPurchaseStart={() => setPaymentInProgress(true)}
					onPurchaseEnd={() => setPaymentInProgress(false)}
				/>

				{/* Кредиты не сгорают — инфо-строка сразу под тарифами */}
				<p className="text-center text-sm text-muted px-4 -mt-4">
					💡{" "}
					<span className="text-accent-strong font-semibold">
						{t("packages.no_expiry_highlight", { defaultValue: "Кредиты не сгорают" })}
					</span>
					. {t("packages.no_expiry_rest", { defaultValue: "Используйте их в любое удобное время." })}
				</p>

				{/* На что хватит? — интерактивный калькулятор по сценарию использования (п.14 ТЗ) */}
				<WhatsEnoughCalculator />

				{/* Как списываются кредиты — короткое объяснение + раскрывающаяся
				    таблица по моделям (принцип ТЗ: не выводить большую таблицу
				    по умолчанию) */}
				<CollapsibleCreditsExplainer />

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
									"Получайте бонусные кредиты за каждого нового пользователя, зарегистрированного по вашему реферальному коду.",
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
