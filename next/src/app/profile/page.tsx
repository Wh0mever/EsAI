// ProfilePage.tsx
"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { CiCircleCheck } from "react-icons/ci";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import UserProfile from "@/components/profile/UserProfile";
import UserPlan from "@/components/profile/UserPlan";
import UserCardSaveSimple from "@/app/profile/components/UserCardSaveSimple";

const checkHasCard = (user?: { card?: any }) => {
	const cardToken = (user?.card?.card_token || "").trim();
	const cardHash = (user?.card?.card_hash || "").trim();
	return Boolean(cardToken || cardHash || user?.card?.card_id);
};


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
	const [isLoadingProfile, setIsLoadingProfile] = useState(true);


	useEffect(() => {
		let mounted = true;
		const loadProfile = async () => {
			try {
				const responseData = await fetchData("users/profile/", "get", null, true);
				if (!mounted) return;
				setProfileData(responseData?.data || {});
			} finally {
				if (mounted) {
					setIsLoadingProfile(false);
				}
			}
		};
		loadProfile();
		return () => {
			mounted = false;
		};
	}, []);

	const shouldShowAlert = !isLoadingProfile && !profileData?.subscription && !checkHasCard(profileData?.user);
	const handleUnsubscribe = async () => {
		const response = await fetchData("plans/me/unsubscribe/", "post", {}, true);
		if (response.ok && response.data) {
			setProfileData((prev) => ({ ...prev, subscription: response.data }));
		}
	};

    return (
        <main className="mx-auto pt-80 pb-20 overflow-hidden relative">
            <Breadcrumb />
            <div className="max-w-4xl mx-auto flex flex-col gap-3 scale-z-50 px-2">
                {shouldShowAlert && <ProfileAlert t={t} />}

				<UserProfile t={t} data={profileData} />
                <UserCardSaveSimple data={profileData?.user} />
                <UserPlan t={t} data={profileData} onUnsubscribe={handleUnsubscribe} />
            </div>
        </main>
    );
}
