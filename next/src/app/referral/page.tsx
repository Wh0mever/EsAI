"use client";

import "@/assets/style.scss";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import Cookies from "js-cookie";
import { FiCopy, FiCheck } from "react-icons/fi";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import { fetchData } from "@/tools/fetchData";

// Public site origin used to build the referral link. Falls back to the
// production host so links are stable even when copied from another domain.
const SITE_ORIGIN = "https://esai.kg";

// Resolve a referral code from the profile response. The backend may expose it
// under several names; we probe the known candidates and fall back to the user id.
function resolveReferralCode(profile: any): string | null {
	const user = profile?.user ?? profile ?? {};
	const candidate =
		user.referral_code ??
		user.ref_code ??
		user.referral ??
		user.invite_code ??
		profile?.referral_code ??
		user.uid ??
		user.id;
	if (candidate === null || candidate === undefined) return null;
	const code = String(candidate).trim();
	return code.length ? code : null;
}

export default function Referral() {
	const { t } = useTranslation("common");
	const [authed, setAuthed] = useState(false);
	const [code, setCode] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [copied, setCopied] = useState(false);

	const link = code ? `${SITE_ORIGIN}/auth/signup?ref=${encodeURIComponent(code)}` : "";

	useEffect(() => {
		const isAuthed = Boolean(Cookies.get("access"));
		setAuthed(isAuthed);
		if (!isAuthed) return;

		let mounted = true;
		setLoading(true);
		(async () => {
			try {
				const res = await fetchData<any>("users/profile/", "GET", null, true);
				if (!mounted) return;
				if (res?.ok) setCode(resolveReferralCode(res.data));
			} finally {
				if (mounted) setLoading(false);
			}
		})();
		return () => {
			mounted = false;
		};
	}, []);

	const copyLink = async () => {
		if (!link) return;
		try {
			await navigator.clipboard.writeText(link);
		} catch {
			// Fallback for non-secure contexts / older browsers.
			try {
				const el = document.createElement("textarea");
				el.value = link;
				el.style.position = "fixed";
				el.style.opacity = "0";
				document.body.appendChild(el);
				el.select();
				document.execCommand("copy");
				document.body.removeChild(el);
			} catch {
				return;
			}
		}
		setCopied(true);
		window.setTimeout(() => setCopied(false), 2000);
	};

	return (
		<main className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
			<Breadcrumb />

			<div className="mx-auto max-w-4xl px-4 py-5">
				<section className="py-10">
					<h1 className="text-3xl font-bold text-center">{t("referral.title")}</h1>
					<p className="text-center text-muted text-base mt-5">{t("referral.subtitle")}</p>
				</section>

				{/* Referral link / sign-in block */}
				<section className="py-2">
					<div className="rounded-2xl border border-border bg-surface-2 p-6">
						<h2 className="text-xl font-semibold text-foreground mb-3">
							{t("referral.your_link", { defaultValue: "Ваша реферальная ссылка" })}
						</h2>

						{!authed ? (
							<div className="flex flex-col gap-3">
								<p className="text-muted text-sm">
									{t("referral.guest_hint", {
										defaultValue: "Войдите, чтобы получить вашу реферальную ссылку.",
									})}
								</p>
								<Link
									href="/auth/signin?next=%2Freferral"
									className="inline-flex w-fit items-center justify-center px-5 py-2.5 rounded-xl bg-accent text-on-accent font-semibold text-sm hover:bg-accent-strong transition-colors"
								>
									{t("referral.sign_in", { defaultValue: "Войти" })}
								</Link>
							</div>
						) : loading ? (
							<p className="text-muted text-sm">{t("common.loading", { defaultValue: "Загрузка..." })}</p>
						) : link ? (
							<div className="flex flex-col sm:flex-row items-stretch gap-3">
								<input
									type="text"
									readOnly
									value={link}
									onFocus={(e) => e.currentTarget.select()}
									className="flex-1 min-w-0 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-foreground select-all"
								/>
								<button
									type="button"
									onClick={copyLink}
									className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm px-5 py-2.5 hover:bg-accent-strong transition-colors cursor-pointer shrink-0"
								>
									{copied ? <FiCheck /> : <FiCopy />}
									{copied
										? t("referral.copied", { defaultValue: "Скопировано" })
										: t("referral.copy", { defaultValue: "Копировать" })}
								</button>
							</div>
						) : (
							<p className="text-muted text-sm">
								{t("referral.no_code", {
									defaultValue:
										"Реферальный код пока недоступен. Он появится после завершения регистрации.",
								})}
							</p>
						)}
					</div>
				</section>

				<section className="py-5">
					<h2 className="text-2xl font-semibold text-center">{t("referral.how_title")}</h2>

					<div className="grid md:grid-cols-3 grid-cols-1 gap-6 mt-5">
						<div className="rounded-xl border border-border p-5 bg-surface-2">
							<h3 className="font-semibold text-lg mb-2 text-foreground">{t("referral.step1.title")}</h3>
							<p className="text-sm text-muted">{t("referral.step1.text")}</p>
						</div>
						<div className="rounded-xl border border-border p-5 bg-surface-2">
							<h3 className="font-semibold text-lg mb-2 text-foreground">{t("referral.step2.title")}</h3>
							<p className="text-sm text-muted">{t("referral.step2.text")}</p>
						</div>
						<div className="rounded-xl border border-border p-5 bg-surface-2">
							<h3 className="font-semibold text-lg mb-2 text-foreground">
								{t("referral.step3.title", { defaultValue: "Бонусные токены" })}
							</h3>
							<p className="text-sm text-muted">
								{t("referral.step3.text", {
									defaultValue: "Вы получаете бонусные токены на баланс за приглашённого друга.",
								})}
							</p>
						</div>
					</div>
				</section>

				<section className="py-5">
					<h2 className="text-2xl font-semibold mb-4 text-center">{t("referral.usage_title")}</h2>
					<ul className="list-disc pl-6 space-y-2 text-muted py-3">
						<li>
							{t("referral.usage1", {
								defaultValue: "Бонусные токены зачисляются на ваш баланс.",
							})}
						</li>
						<li>
							{t("referral.usage2", {
								defaultValue: "Они расходуются так же, как купленные токены.",
							})}
						</li>
						<li>
							{t("referral.usage3", {
								defaultValue: "Чем больше друзей вы пригласите, тем больше бонусных токенов получите.",
							})}
						</li>
					</ul>
				</section>
			</div>
		</main>
	);
}
