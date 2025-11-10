// ProfilePage.tsx
"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { CiCircleCheck } from "react-icons/ci";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import UserProfile from "@/components/profile/UserProfile";
import UserVisa from "@/components/profile/UserPayment";
import UserPlan from "@/components/profile/UserPlan";
import { tokenizeBankCard } from "@/lib/freedompay/pay";
import { Alert } from "@/components/ui/alert/Alert";

function ProfileAlert({ t }: { t: any }) {
	const EmptyPlanAlert = () => (
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
	return EmptyPlanAlert();
}

export default function ProfilePage() {
    const { t } = useTranslation("common");
    const [profileData, setProfileData] = useState<{ subscription?: boolean; user?: any; card?: any }>({});
    const [subscriptionData, setSubscriptionData] = useState<any>(null);
    const [alertOpen, setAlertOpen] = useState(false);
    const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");
    const [alertTitle, setAlertTitle] = useState("");
    const [alertMessage, setAlertMessage] = useState("");

	useEffect(() => {
		fetchData("users/profile/", "get", null, true).then((responseData) => {
			setProfileData(responseData?.data);
		});
	}, []);

    // Bind card only: get token, no payment
    async function handleSubmitCard(card: {
        number: string;
        expMonth: string;
        expYear: string;
        cvv: string; // unused here
        holder: string;
    }) {
    try {
            const token = await tokenizeBankCard({
                number: card.number,
                holder: card.holder,
                expMonth: card.expMonth,
                expYear: card.expYear,
                cvv: card.cvv,
            });

            const brand = /^4/.test(card.number)
                ? "VISA"
                : /^(5[1-5]|2(2[2-9]|[3-6]\d|7[01]))/.test(card.number)
                ? "MASTERCARD"
                : "CARD";
            const last4 = card.number.replace(/\D+/g, "").slice(-4);
            const expiry = `${card.expMonth}/${card.expYear.slice(-2)}`;

            // Persist token + public card meta on backend
            const bind = await fetchData("users/card/bind/", "POST", {
                token,
                brand,
                last4,
                exp_month: Number(card.expMonth),
                exp_year: Number(card.expYear.length === 2 ? `20${card.expYear}` : card.expYear),
                card_holder: card.holder,
            }, true);
            if (!bind.ok) throw new Error(bind.error || "Bind failed");

            // Refresh profile to reflect new card
            fetchData("users/profile/", "GET", null, true).then((responseData) => {
                if (responseData?.data) setProfileData(responseData.data);
            });

            setAlertType("success");
            setAlertTitle(t("status_extended.success"));
            setAlertMessage("");
            setAlertOpen(true);
        } catch (e: any) {
            console.error("FP tokenize error:", e?.response || e);
            const msg = e?.response?.error_message || e?.message || "";
            const friendly = (typeof msg === "string" && /<html|<!DOCTYPE/i.test(msg)) ? "Server error" : (msg || "Tokenize error");
            setAlertType("error");
            setAlertTitle(t("status_extended.error"));
            setAlertMessage(String(friendly));
            setAlertOpen(true);
        }
    }

    return (
        <main className="mx-auto pt-80 pb-20 overflow-hidden relative">
            <Breadcrumb />
            <div className="max-w-4xl mx-auto flex flex-col gap-3 scale-z-50 px-2">
                {!profileData?.subscription && <ProfileAlert t={t} />}

				<UserProfile t={t} data={profileData} />
				<UserVisa t={t} isCardLinked={false} onSubmitCard={handleSubmitCard} cardData={profileData?.card} />
                {/* <div id="fp-3ds" className="w-full max-w-md max-h-[400px] min-h-0 p-0" /> */}
                <UserPlan t={t} data={profileData} />
            </div>
            <Alert
              show={alertOpen}
              onClose={() => setAlertOpen(false)}
              type={alertType}
              title={alertTitle}
              message={alertMessage}
              position="top"
              autoClose={true}
              autoCloseDuration={3500}
            />
        </main>
    );
}
