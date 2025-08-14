'use client';

import React from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoExitOutline } from "react-icons/io5";
import Link from "next/link";

export default function UserPlan({ t, data }: { t: any; data: any }) {
    const CurrentPlan = () => {
        return (
            <div className="flex flex-col gap-3 w-full">
                <div className="flex justify-between items-center">
                    <h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
                    <i className="text-7xl text-gray-500">
                        <IoExitOutline />
                    </i>
                </div>
                <p>
                    <strong>{t("profile.plan")}:</strong>
                </p>
                <p>
                    <strong>{t("profile.price")}:</strong>
                </p>
                <p>
                    <strong>{t("profile.write-off")}:</strong>
                </p>
                <Button className="px-6 py-2 rounded-xl bg-rose-500 hover:bg-rose-700 w-fit">
                    {t("profile.unsubscribe")}
                </Button>
            </div>
        );
    };
    const EmptyPlan = () => {
        return (
            <div className="flex flex-col gap-3 w-full">
                <div className="flex justify-between items-center">
                    <h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
                    <img src="/images/logo/head.svg" alt="" className="w-15" />
                </div>

                <div className="flex flex-col gap-3">
                    <h3 className="text-3xl">{t("profile.plan_info.empty_title")}</h3>
                    <p className="text-lg">{t("profile.plan_info.empty_text")}</p>
                    <p className="text-md text-gray-400">{t("profile.plan_info.empty_text2")}</p>
                    <Link href="pricing" className="text-lg text-yellow-400 hover:text-yellow-500 duration-300">
                        {t("profile.pricing")}
                    </Link>
                </div>
            </div>
        );
    };

    let view = null;
    if (data && data.plan) {
        view = <CurrentPlan />;
    } else if (data && !data.plan) {
        view = <EmptyPlan />;
    }

    return <Card>{view}</Card>;
}
