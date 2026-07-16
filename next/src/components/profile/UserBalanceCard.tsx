"use client";

import React from "react";
import Link from "next/link";
import { Card } from "@/components/ui/cards/Cards";

type Props = {
	t: (k: string, options?: Record<string, unknown>) => string;
	data: any;
};

/**
 * UserBalanceCard — карточка баланса в профиле (кредитная модель EsAI).
 * Заменяет старую подписочную карточку Vokalo (UserPlan): здесь нет «подписок»,
 * «7 дней», music/image/song — оплата по факту использования пакетами кредитов.
 */
export default function UserBalanceCard({ t, data }: Props) {
	const user = data?.user || {};
	const isUnlimited = Boolean(user?.is_unlimited);
	const isPaid = Boolean(user?.is_paid);
	const balance = Number(user?.token_balance ?? 0);

	const tierLabel = isUnlimited
		? t("profile.tier.unlimited", { defaultValue: "Безлимит (тест)" })
		: isPaid
		? t("profile.tier.paid", { defaultValue: "Платный" })
		: t("profile.tier.free", { defaultValue: "Бесплатный" });

	return (
		<Card>
			<div className="flex flex-col gap-4 w-full">
				<div className="flex items-center justify-between gap-3">
					<h2 className="text-xl font-bold">
						{t("profile.balance_title", { defaultValue: "Баланс" })}
					</h2>
					<span className="text-xs px-3 py-1 rounded-full border border-border text-muted shrink-0">
						{tierLabel}
					</span>
				</div>

				<div className="flex items-baseline gap-2">
					<span className="text-4xl font-bold text-accent">
						{isUnlimited ? "∞" : balance.toLocaleString()}
					</span>
					<span className="text-muted">
						{t("topup.credits", { defaultValue: "кредитов" })}
					</span>
				</div>

				<p className="text-muted text-sm leading-relaxed">
					{t("profile.balance_hint", {
						defaultValue:
							"Оплата по факту использования. Пополняйте баланс пакетами кредитов — без подписок и лишних трат.",
					})}
				</p>

				<div className="flex flex-wrap gap-2">
					<Link
						href="/pricing"
						className="w-fit px-6 py-2 rounded-xl bg-accent text-on-accent font-semibold hover:bg-accent-strong transition-colors"
					>
						{t("balance.topup", { defaultValue: "Пополнить" })}
					</Link>
					<Link
						href="/"
						className="w-fit px-6 py-2 rounded-xl bg-surface-2 hover:bg-surface-3 duration-300"
					>
						{t("profile.open_chat", { defaultValue: "Открыть чат" })}
					</Link>
				</div>
			</div>
		</Card>
	);
}
