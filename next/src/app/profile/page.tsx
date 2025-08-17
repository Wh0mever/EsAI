"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { useEffect, useState } from "react";
import { CiCircleCheck } from "react-icons/ci";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import UserProfile from "@/components/profile/UserProfile";
import UserVisa from "@/components/profile/UserPayment";
import UserPlan from "@/components/profile/UserPlan";
import { payWithBankCard } from "@/lib/freedompay/pay";

async function waitForSDK(timeout = 5000) {
	const start = Date.now();
	return new Promise<void>((resolve, reject) => {
		(function check() {
			if (typeof window !== "undefined" && window.FreedomPaySDK) {
				resolve();
				return;
			}
			if (Date.now() - start > timeout) {
				reject(new Error("FreedomPaySDK is not loaded"));
				return;
			}
			requestAnimationFrame(check);
		})();
	});
}

function ProfileAlert({ t }: { t: any }) {
	const EmptyPlanAlert = () => {
		return (
			<div className="w-full p-10 bg-neutral-900 border border-green-700 rounded-3xl flex flex-col gap-2">
				<div className="flex gap-2 items-center">
					<h3 className="text-xl">{t("profile.plan_info.empty_alert_title")}</h3>
					<i className="text-2xl text-green-700">
						<CiCircleCheck />
					</i>
				</div>
				<p className="text-lg text-gray-400">{t("profile.plan_info.empty_alert_text")}</p>
				<p className="text-gray-400">{t("profile.plan_info.empty_alert_text2")}</p>
			</div>
		);
	};

	return EmptyPlanAlert();
}

export default function ProfilePage() {
	const { t } = useTranslation("common");
	const [profileData, setProfileData] = useState<{ plan?: boolean; user?: any }>({});

	useEffect(() => {
		fetchData("users/profile/", "get", null, true).then((responseData) => {
			setProfileData(JSON.parse(responseData?.data));
		});
	}, []);

	async function handleSubmitCard(card: {
		number: string;
		expMonth: string;
		expYear: string;
		cvv: string;
		holder: string;
	}) {
		const res = await payWithBankCard(
			{
				number: card.number,
				holder: card.holder,
				expMonth: card.expMonth,
				expYear: card.expYear,
				cvv: card.cvv,
			},
			{
				orderId: `order_${Date.now()}`,
				amount: 1,
				currency: "KGS",
				description: "Test payment",
				test: true,
				user: { email: "test@example.com" },
			},
			"fp-3ds"
		);
		console.log("FreedomPay result:", res);
	}

	return (
		<main className="mx-auto pt-80 pb-20 overflow-hidden relative px-4">
			<Breadcrumb />
			<div className="max-w-4xl mx-auto flex flex-col gap-3 scale-z-50">
				{!profileData?.plan && <ProfileAlert t={t} />}

				<UserProfile t={t} data={profileData} />
				<UserVisa t={t} isCardLinked={false} onSubmitCard={handleSubmitCard} />
				{/* 3DS контейнер вне формы */}
				<div id="fp-3ds" className="w-full max-w-md max-h-[400px]" />
				<UserPlan t={t} data={profileData} />
			</div>
		</main>
	);
}
