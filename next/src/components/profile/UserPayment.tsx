// components/UserVisa.tsx
"use client";

import React, { useRef, useState, useEffect } from "react";
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
        __FP_ENV__?: { pk?: string; token?: string; merchantId?: string };
    }
}

/* ---------- FP SDK helpers ---------- */
function isFPDebug() {
    const v = (process.env.NEXT_PUBLIC_FREEDOM_PAY_DEBUG || "").toLowerCase();
    return v === "1" || v === "true" || v === "full" || v === "on";
}

function isFPTestMode(): 0 | 1 {
    const raw = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST
        || (process.env as any).NEXT_PUBLIC_FREEDOM_PAY_TEST_MODE
        || (process.env as any).NEXT_PUBLIC_FREEDOMPAY_TEST
        || "").toString().trim().toLowerCase();
    if (raw === "1" || raw === "true" || raw === "yes" || raw === "on" || raw === "test" || raw === "sandbox") {
        return 1;
    }
    return 0;
}

function maskPan(pan: string) {
    const d = (pan || "").replace(/\D+/g, "");
    if (d.length <= 8) return d.replace(/\d/g, "*");
    return d.slice(0, 6) + d.slice(6, -4).replace(/\d/g, "*") + d.slice(-4);
}

function mask(str: string) {
    return (str || "").replace(/./g, "*");
}

function normalizePemLike(str: string) {
	let s = (str || "").replace(/\\n/g, "\n").replace(/\\r/g, "\r").trim();
	if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) s = s.slice(1, -1).trim();
	return s;
}

function getPublicKeyForSDK(): string {
    const raw = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
    let pk = normalizePemLike(raw);
    if (pk.includes("BEGIN PUBLIC KEY") && pk.includes("END PUBLIC KEY")) {
        const m = pk.match(/-----BEGIN PUBLIC KEY-----([\s\S]*?)-----END PUBLIC KEY-----/);
        if (m) pk = m[1];
    }
    pk = pk.replace(/\s+/g, "");
    return pk;
}

type FPEnv = { pk: string; token: string; merchantId?: string };

async function loadEnvAtRuntime(): Promise<FPEnv> {
  const pkInline = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
  const tokenInline = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || "";
  const merchantInline = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || "";
  if (pkInline && tokenInline) return { pk: pkInline, token: tokenInline, merchantId: merchantInline };
  if (typeof window === "undefined") return { pk: "", token: "" } as FPEnv;
  // Try window-injected values from layout first (no API needed)
  if (window.__FP_ENV__ && (window.__FP_ENV__.pk || window.__FP_ENV__.token)) {
    return {
      pk: window.__FP_ENV__.pk || "",
      token: window.__FP_ENV__.token || "",
      merchantId: window.__FP_ENV__.merchantId || "",
    } as FPEnv;
  }
	try {
		const res = await fetch("/api/freedompay-env", { cache: "no-store" });
		if (!res.ok) throw new Error("env fetch failed");
		const data = await res.json();
		return {
			pk: data?.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "",
			token: data?.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || "",
		};
	} catch (_) {
        return { pk: "", token: "" } as FPEnv;
}
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
    const env: FPEnv = await loadEnvAtRuntime();
    let pk = normalizePemLike(env.pk);
    if (pk.includes("BEGIN PUBLIC KEY") && pk.includes("END PUBLIC KEY")) {
        const m = pk.match(/-----BEGIN PUBLIC KEY-----([\s\S]*?)-----END PUBLIC KEY-----/);
        if (m) pk = m[1];
    }
    const token = (env.token || "").trim();
    if (!pk) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY");
    if (!token) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_TOKEN");
    const sdk = await waitSDK();
    const publicKey = pk.replace(/\s+/g, "");
    try {
        if (isFPDebug()) {
            // Do not log full token/key by default
            console.log("[FP] setup", {
                publicKeyLength: publicKey.length,
                token: mask(token),
                merchantId: env.merchantId || "",
            });
        }
    } catch {}
    sdk.setup(publicKey, token);
    return sdk;
}

async function tokenizeCard(input: { number: string; expMonth: string; expYear: string; holder: string; cvv?: string }) {
    const sdk = await setupSDK();
    const payload: any = {
      type: "bank_card",
      options: {
        card_number: input.number.replace(/\D+/g, ""),
        card_holder_name: input.holder.trim().replace(/\s+/g, " ").toUpperCase(),
        card_exp_month: input.expMonth.trim().padStart(2, "0"),
        card_exp_year: input.expYear.trim().slice(-2),
      },
    };
    if (input.cvv && /^\d{3,4}$/.test(input.cvv)) {
      payload.options.card_cvv = Number(input.cvv.trim());
    }
    const testFlag = isFPTestMode();
    try {
        if (isFPDebug()) {
            console.log("[FP] tokenize request", {
                type: payload.type,
                options: {
                    card_number: maskPan(payload.options.card_number),
                    card_holder_name: payload.options.card_holder_name,
                    card_exp_month: payload.options.card_exp_month,
                    card_exp_year: payload.options.card_exp_year,
                    card_cvv: payload.options.card_cvv ? mask(String(payload.options.card_cvv)) : undefined,
                },
                test: testFlag,
            });
        }
    } catch {}
    const resp = await (testFlag ? sdk.tokenize(payload, { test: testFlag }) : sdk.tokenize(payload));
    try {
        if (isFPDebug()) {
            console.log("[FP] tokenize response", {
                ok: !!resp?.token,
                tokenLength: resp?.token ? String(resp.token).length : 0,
                raw: resp,
            });
        }
    } catch {}
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

export function UserVisa({
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
		const cardRefs = [
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
		];
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
                    cvv: payload.cvv,
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
					<Button
						type="submit"
						disabled={loading}
						className="px-3 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-700 mt-5"
					>
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
					<Button
						onClick={() => setRelink(true)}
						className="px-6 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 duration-300 mt-5"
					>
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
						<i className="text-7xl text-gray-500">
							<RiVisaLine />
						</i>
						<i className="text-7xl text-gray-500">
							<FaCcMastercard />
						</i>
					</div>
				</div>

				{hasCard ? <VisaInfo cardData={cardData} /> : <VisaForm />}
			</div>
		</Card>
	);
}

export function UserCardSaveSimple({}) {
	return (
		<div>Simple</div>
	);
}