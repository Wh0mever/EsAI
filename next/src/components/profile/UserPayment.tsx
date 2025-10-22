// components/UserVisa.tsx
"use client";

import React, { useRef, useState } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { FaCcMastercard } from "react-icons/fa";
import { RiVisaLine } from "react-icons/ri";

type PropsVisa = {
  t: any;
  isCardLinked: boolean;
  cardData?: {
    brand?: string;
    last4?: string;
    expiry?: string;
    card_holder?: string;
    exp_month?: number | string;
    exp_year?: number | string;
  };
  onLinkCard?: () => void;
  onChangeCard?: () => void;
  onSubmitCard?: (card: {
    number: string;
    expMonth: string;
    expYear: string;
    cvv: string;
    holder: string;
  }) => Promise<void> | void;
  threeDSContainerId?: string;
};

declare global {
  interface Window {
    FreedomPaySDK?: any;
    FreedomPay?: any;
    freedomPay?: any;
    __fp_script_loaded__?: boolean;
  }
}

/* ---------- FP SDK helpers ---------- */
function normalizePemLike(str: string) {
  let s = (str || "").replace(/\\n/g, "\n").replace(/\\r/g, "\r").trim();
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) s = s.slice(1, -1).trim();
  return s;
}

function getPublicKeyForSDK(): string {
  const raw = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
  const pk = normalizePemLike(raw);
  if (pk.includes("BEGIN PUBLIC KEY") && pk.includes("END PUBLIC KEY")) return pk;
  if (/^[A-Za-z0-9+/=]+$/.test(pk) && pk.length > 100) return pk;
  return pk.replace(/\s+/g, "");
}

function assertEnv() {
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY");
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_TOKEN");
}

async function waitSDK(timeoutMs = 12000): Promise<any> {
  if (typeof window === "undefined") throw new Error("FreedomPaySDK must run in browser");
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const g = window.FreedomPaySDK || window.FreedomPay || window.freedomPay;
      if (g) {
        if (!window.FreedomPaySDK) window.FreedomPaySDK = g;
        return resolve(window.FreedomPaySDK);
      }
      if (Date.now() - start > timeoutMs) {
        const loaded = !!window.__fp_script_loaded__;
        return reject(new Error(loaded ? "FreedomPaySDK global not exported" : "FreedomPaySDK is not loaded"));
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

async function setupSDK() {
  assertEnv();
  const sdk = await waitSDK();
  const publicKey = getPublicKeyForSDK();
  const token = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN as string).trim();
  sdk.setup(publicKey, token);
  return sdk;
}

async function tokenizeCard(input: {
  number: string; expMonth: string; expYear: string; holder: string;
}) {
  const sdk = await setupSDK();
  const payload = {
    type: "bank_card",
    options: {
      card_number: input.number.replace(/\D+/g, ""),
      card_holder_name: input.holder.trim(),
      card_exp_month: input.expMonth.trim(),
      card_exp_year: input.expYear.trim().slice(-2),
    },
  };
  const resp = await sdk.tokenize(payload);
  if (!resp?.token) throw new Error("Tokenize failed");
  return String(resp.token);
}

function detectBrand(num: string) {
  const n = num.replace(/\D+/g, "");
  if (/^4\d{12,18}$/.test(n)) return "VISA";
  if (/^(5[1-5]|2(2[2-9]|[3-6]\d|7[01]))/.test(n)) return "MASTERCARD";
  return "CARD";
}
/* ------------------------------------ */

export default function UserVisa({
  t,
  isCardLinked,
  cardData,
  onLinkCard,
  onChangeCard,
  onSubmitCard,
  threeDSContainerId = "fp-3ds",
}: PropsVisa) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [relink, setRelink] = useState(false);
  const hasCard = !!cardData && !relink;

  const VisaForm = () => {
    const cardRefs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];
    const mmRef = useRef<HTMLInputElement>(null);
    const yyRef = useRef<HTMLInputElement>(null);
    const cvvRef = useRef<HTMLInputElement>(null);
    const holderRef = useRef<HTMLInputElement>(null);

    const handleCardInput = (e: React.ChangeEvent<HTMLInputElement>, index: number) => {
      const value = e.target.value.replace(/\D+/g, "").slice(0, 4);
      e.currentTarget.value = value;
      if (value.length === 4 && index < cardRefs.length - 1) {
        cardRefs[index + 1].current?.focus();
      }
    };

    const onSubmitLocal = async (e: React.FormEvent) => {
      e.preventDefault();
      if (loading) return;
      setErr(null);
      setLoading(true);
      try {
        const number =
          (cardRefs[0].current?.value || "") +
          (cardRefs[1].current?.value || "") +
          (cardRefs[2].current?.value || "") +
          (cardRefs[3].current?.value || "");

        const payload = {
          number: number.replace(/\D+/g, ""),
          expMonth: (mmRef.current?.value || "").replace(/\D+/g, ""),
          expYear: (yyRef.current?.value || "").replace(/\D+/g, ""),
          cvv: (cvvRef.current?.value || "").replace(/\D+/g, ""),
          holder: (holderRef.current?.value || "").trim(),
        };

        const token = await tokenizeCard({
          number: payload.number,
          expMonth: payload.expMonth,
          expYear: payload.expYear,
          holder: payload.holder,
        });

        const brand = detectBrand(payload.number);
        const last4 = payload.number.slice(-4);
        const expiry = `${payload.expMonth}/${payload.expYear.slice(-2)}`;

        window.dispatchEvent(
          new CustomEvent("fp:card_tokenized", {
            detail: { token, brand, last4, expiry },
          })
        );

        onLinkCard?.();
        await onSubmitCard?.(payload);
        setRelink(false);
      } catch (e: any) {
        setErr(e?.message || "Tokenize error");
      } finally {
        setLoading(false);
      }
    };

    return (
      <form onSubmit={onSubmitLocal} className="flex flex-col gap-5 justify-center items-start">
        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.card_number")}</label>
          <div className="flex gap-2">
            {cardRefs.map((ref, i) => (
              <input
                className="border-b border-gray-500 p-2 text-center w-2/12 min-w-15"
                key={i}
                type="text"
                maxLength={4}
                inputMode="numeric"
                placeholder="****"
                pattern="\d*"
                ref={ref}
                onChange={(e) => handleCardInput(e, i)}
                required
                disabled={loading}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.expired_date")}</label>
          <div className="flex gap-2 items-center">
            <input
              ref={mmRef}
              type="text"
              placeholder="MM"
              maxLength={2}
              inputMode="numeric"
              pattern="\d*"
              required
              className="text-center px-3 py-2 border-b border-gray-500 w-2/12 min-w-15"
              disabled={loading}
            />
            <span className="text-gray-500">/</span>
            <input
              ref={yyRef}
              type="text"
              placeholder="YY"
              maxLength={4}
              inputMode="numeric"
              pattern="\d*"
              required
              className="text-center px-3 py-2 border-b border-gray-500 w-2/12 min-w-15"
              disabled={loading}
            />
          </div>
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">CVV</label>
          <input
            ref={cvvRef}
            type="password"
            maxLength={4}
            inputMode="numeric"
            placeholder="***"
            pattern="\d*"
            required
            className="w-2/12 min-w-15 text-center px-3 py-2 border-b border-gray-500"
            disabled={loading}
          />
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.fullname")}</label>
          <input
            ref={holderRef}
            type="text"
            name="card_name"
            placeholder="John Doe"
            required
            className="w-3/12 px-3 py-2 border-b border-gray-500"
            disabled={loading}
          />
        </div>

        <div id={threeDSContainerId} className="hidden" />

        {err && <p className="text-red-500 text-sm">{err}</p>}

        <div className="flex gap-2">
          <Button type="submit" disabled={loading} className="px-3 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-700 mt-5">
            {loading ? t("common.processing") : t("profile.add_card")}
          </Button>
          {hasCard && (
            <Button
              type="button"
              disabled={loading}
              className="px-3 py-2 rounded-xl bg-neutral-700 hover:bg-neutral-600 mt-5"
              onClick={() => setRelink(false)}
            >
              {t("common.cancel")}
            </Button>
          )}
        </div>
      </form>
    );
  };

  const VisaInfo = ({ cardData }: { cardData: any }) => {
    const holder = cardData.card_holder || cardData.holder || "";
    const yy = String(cardData.exp_year ?? "").slice(-2);
    const mm = String(cardData.exp_month ?? "").padStart(2, "0");
    const expiry = cardData.expiry || `${mm}/${yy}`;

    return (
      <>
        {holder && (
          <p>
            <strong>{t("profile.fullname")}:</strong> {holder}
          </p>
        )}
        <p>
          <strong>{t("profile.last4")}:</strong> **** **** **** {cardData.last4 || "••••"}
        </p>
        <p>
          <strong>{t("profile.period")}:</strong> {expiry}
        </p>
        <div className="flex gap-2">
          <Button onClick={() => setRelink(true)} className="px-6 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 duration-300 mt-5">
            {t("profile.change")}
          </Button>
        </div>
      </>
    );
  };

  return (
    <Card>
      <div className="flex flex-col gap-3 w-full">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-bold">{t("profile.card")}</h2>
          <div className="flex gap-2">
            <i className="text-7xl text-gray-500"><RiVisaLine /></i>
            <i className="text-7xl text-gray-500"><FaCcMastercard /></i>
          </div>
        </div>

        {hasCard ? <VisaInfo cardData={cardData} /> : <VisaForm />}
      </div>
    </Card>
  );
}
