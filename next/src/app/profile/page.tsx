// ProfilePage.tsx
"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import UserProfile from "@/components/profile/UserProfile";
import UserPlan from "@/components/profile/UserPlan";
import UserCardSaveSimple from "@/app/profile/components/UserCardSaveSimple";

const checkHasCard = (user?: { card?: any }) => {
	const cardToken = (user?.card?.card_token || "").trim();
	const cardHash = (user?.card?.card_hash || "").trim();
	return Boolean(cardToken || cardHash || user?.card?.card_id);
};

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

	const hasCard = checkHasCard(profileData?.user);
	const shouldShowNoCardPaymentNotice = !isLoadingProfile && !hasCard;
    const handleUnsubscribe = async () => {
        const response = await fetchData("plans/me/unsubscribe/", "post", {}, true);
        if (response.ok && response.data) {
            setProfileData((prev) => ({ ...prev, subscription: response.data }));
        }
        return response;
    };

    const handleResume = async () => {
        const response = await fetchData("plans/me/resume/", "post", {}, true);
        if (response.ok && response.data) {
            setProfileData((prev) => ({ ...prev, subscription: response.data }));
        }
        return response;
    };

    return (
        <main className="mx-auto pt-80 pb-20 overflow-hidden relative">
            <Breadcrumb />
            <div className="max-w-4xl mx-auto flex flex-col gap-3 scale-z-50 px-2">
                {shouldShowNoCardPaymentNotice && (
                    <div className="w-full p-6 bg-neutral-900 border border-amber-600/60 rounded-2xl text-amber-100">
                        {t("profile.no_card_payment_notice")}
                    </div>
                )}

				<UserProfile t={t} data={profileData} />
                <UserCardSaveSimple data={profileData?.user} />
                <UserPlan t={t} data={profileData} onUnsubscribe={handleUnsubscribe} onResume={handleResume} />
            </div>
        </main>
    );
}
