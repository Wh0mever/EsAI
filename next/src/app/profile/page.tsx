// ProfilePage.tsx
"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import Link from "next/link";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import UserProfile from "@/components/profile/UserProfile";
import UserBalanceCard from "@/components/profile/UserBalanceCard";
import PromoActivate from "@/components/cabinet/PromoActivate";
import { FiSend, FiUsers } from "react-icons/fi";

// Профиль в токенной модели EsAI: данные аккаунта + баланс/пополнение.
// Старая подписочная карточка (UserPlan: «подписка», «7 дней», music/image/song,
// «нет активной подписки») удалена — она противоречила pay-as-you-go.
export default function ProfilePage() {
	const { t } = useTranslation("common");
	const [profileData, setProfileData] = useState<{ user?: any; card?: any }>({});

	useEffect(() => {
		let mounted = true;
		const loadProfile = async () => {
			const responseData = await fetchData("users/profile/", "get", null, true);
			if (!mounted) return;
			setProfileData(responseData?.data || {});
		};
		loadProfile();
		return () => {
			mounted = false;
		};
	}, []);

	// Промокод начислил кредиты → обновляем баланс в карточке без перезагрузки.
	const handleCredited = (balance: number) => {
		setProfileData((prev) => ({
			...prev,
			user: { ...(prev?.user || {}), token_balance: balance },
		}));
	};

	return (
		<main className="mx-auto pt-80 pb-20 overflow-hidden relative">
			<Breadcrumb />
			<div className="max-w-4xl mx-auto flex flex-col gap-3 px-2">
				<UserProfile t={t} data={profileData} />
				<UserBalanceCard t={t} data={profileData} />

				<PromoActivate onCredited={handleCredited} />

				{/* Быстрые ссылки в кабинет: перевод кредитов и партнёрство */}
				<div className="grid sm:grid-cols-2 grid-cols-1 gap-3">
					<Link
						href="/transfer"
						className="flex items-center gap-3 rounded-2xl border border-border bg-surface p-6 hover:border-accent/60 transition-colors"
					>
						<span className="w-11 h-11 rounded-xl bg-accent-soft grid place-items-center shrink-0">
							<FiSend className="text-accent text-xl" />
						</span>
						<span className="min-w-0">
							<span className="block font-semibold text-foreground">
								{t("transfer.title", { defaultValue: "Перевести кредиты" })}
							</span>
							<span className="block text-sm text-muted">
								{t("transfer.card_hint", { defaultValue: "Отправить кредиты другому пользователю" })}
							</span>
						</span>
					</Link>
					<Link
						href="/referral"
						className="flex items-center gap-3 rounded-2xl border border-border bg-surface p-6 hover:border-accent/60 transition-colors"
					>
						<span className="w-11 h-11 rounded-xl bg-accent-soft grid place-items-center shrink-0">
							<FiUsers className="text-accent text-xl" />
						</span>
						<span className="min-w-0">
							<span className="block font-semibold text-foreground">
								{t("partner.title", { defaultValue: "Партнёрство" })}
							</span>
							<span className="block text-sm text-muted">
								{t("partner.card_hint", { defaultValue: "Приглашайте друзей и получайте кредиты" })}
							</span>
						</span>
					</Link>
				</div>
			</div>
		</main>
	);
}
