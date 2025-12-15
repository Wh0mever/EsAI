"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { fetchData } from "@/tools/fetchData";
import { useTranslation } from "react-i18next";


export default function UserCardSaveSimple({ data }: any) {
  const { t } = useTranslation("common");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cardToken = (data?.card?.card_token || "").trim();
  const cardHash = (data?.card?.card_hash || "").trim();
  const cardMonth = (data?.card?.card_month || "").trim();
  const cardYear = (data?.card?.card_year || "").trim();
  const cardExpiry = [cardMonth, cardYear].filter(Boolean).join("/");
  const hasCard = Boolean(cardToken || cardHash || data?.card?.card_id);

  const startBind = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchData<{ redirect_url?: string }>("payments/card/bind/start/", "POST", null, true);
      const url = result?.data?.redirect_url;
      if (!result.ok || !url) {
        throw new Error(result.error || "FreedomPay session error");
      }
      window.location.href = url;
    } catch (e: any) {
      setError(e?.message || "FreedomPay request failed");
      setLoading(false);
    }
  };

  return (
    <Card>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col justify-between">
          <h2 className="text-xl font-bold">{t("profile.card")}</h2>
          {hasCard && <span className="text-sm text-green-500 font-semibold">{t("profile.card_bind_ready_badge")}</span>}
        </div>
        {!hasCard && <p className="text-gray-400 text-sm">{t("profile.card_bind_description")}</p>}
        {error && <p className="text-sm text-red-500">{error}</p>}
        {!hasCard && (
          <div>
            <Button
              type="button"
              onClick={startBind}
              disabled={loading}
              className="px-5 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60"
            >
              {loading ? t("profile.card_bind_loading") : t("profile.card_bind_button")}
            </Button>
          </div>
        )}
        {hasCard && (
          <>
            <div className="text-sm text-gray-300 space-y-1">
              <p>{t("profile.card_bind_ready_text")}</p>
              <p className="text-base font-mono">
                <span className="text-gray-400">{t("profile.card_hash_label")}:</span>{" "}
                {cardHash || t("profile.card_hash_unknown")}
              </p>
              <p>
                <span className="text-gray-400">{t("profile.card_expiry_label")}:</span>{" "}
                <span className="font-semibold">{cardExpiry || t("profile.card_expiry_unknown")}</span>
              </p>
            </div>
            <div>
              <Button
                type="button"
                onClick={startBind}
                disabled={loading}
                className="px-5 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60"
              >
                {loading ? t("profile.card_bind_loading") : t("profile.card_bind_new_button")}
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
