"use client";

import "@/assets/style.scss";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import Cookies from "js-cookie";
import { FiCopy, FiCheck, FiUsers, FiTrendingUp } from "react-icons/fi";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import { fetchData } from "@/tools/fetchData";

// Public site origin used to build the referral link. Falls back to the
// production host so links are stable even when copied from another domain.
const SITE_ORIGIN = "https://esai.kg";

type ReferralHistoryRow = { date: string; amount: number };

type ReferralStats = {
	referral_uid?: string;
	link?: string;
	invited_count?: number;
	total_earned?: number;
	history?: ReferralHistoryRow[];
};

function formatDate(raw?: string): string {
	if (!raw) return "";
	const d = new Date(raw);
	if (Number.isNaN(d.getTime())) return raw;
	return d.toLocaleString();
}

export default function Referral() {
	const { t } = useTranslation("common");
	const [authed, setAuthed] = useState(false);
	const [loading, setLoading] = useState(false);
	const [stats, setStats] = useState<ReferralStats | null>(null);
	const [copied, setCopied] = useState(false);

	// Ссылка: берём готовую из ответа бэка, иначе собираем из referral_uid.
	const code = stats?.referral_uid ? String(stats.referral_uid).trim() : "";
	const link =
		stats?.link ||
		(code ? `${SITE_ORIGIN}/auth/signup?ref=${encodeURIComponent(code)}` : "");

	useEffect(() => {
		const isAuthed = Boolean(Cookies.get("access"));
		setAuthed(isAuthed);
		if (!isAuthed) return;

		let mounted = true;
		setLoading(true);
		(async () => {
			try {
				const res = await fetchData<ReferralStats>("users/referral/stats/", "GET", null, true);
				if (!mounted) return;
				if (res?.ok && res.data) setStats(res.data);
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

	const invited = Number(stats?.invited_count ?? 0);
	const earned = Number(stats?.total_earned ?? 0);
	const history = Array.isArray(stats?.history) ? stats!.history! : [];

	return (
		<main className="mx-auto lg:pt-80 pt-50 pb-20 overflow-hidden relative">
			<Breadcrumb />

			<div className="mx-auto max-w-4xl px-4 py-5">
				<section className="py-8">
					<h1 className="text-3xl font-bold text-center">
						{t("partner.title", { defaultValue: "Партнёрство" })}
					</h1>
					<p className="text-center text-muted text-base mt-4">
						{t("partner.subtitle", {
							defaultValue:
								"Приглашайте друзей и получайте кредиты с их пополнений — пожизненно.",
						})}
					</p>
				</section>

				{/* Реферальная ссылка / вход */}
				<section className="py-2">
					<div className="rounded-2xl border border-border bg-surface p-6">
						<h2 className="text-xl font-semibold text-foreground mb-3">
							{t("partner.your_link", { defaultValue: "Ваша партнёрская ссылка" })}
						</h2>

						{!authed ? (
							<div className="flex flex-col gap-3">
								<p className="text-muted text-sm">
									{t("partner.guest_hint", {
										defaultValue: "Войдите, чтобы получить вашу партнёрскую ссылку.",
									})}
								</p>
								<Link
									href="/auth/signin?next=%2Freferral"
									className="inline-flex w-fit items-center justify-center px-5 py-2.5 rounded-xl bg-accent text-on-accent font-semibold text-sm hover:bg-accent-strong transition-colors"
								>
									{t("auth.login", { defaultValue: "Войти" })}
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
									className="flex-1 min-w-0 rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground select-all"
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
										"Партнёрский код пока недоступен. Он появится после завершения регистрации.",
								})}
							</p>
						)}
					</div>
				</section>

				{/* Статистика: приглашено + общий доход */}
				{authed && (
					<section className="grid sm:grid-cols-2 grid-cols-1 gap-4 py-4">
						<div className="rounded-2xl border border-border bg-surface p-6">
							<div className="flex items-center gap-2 text-muted mb-2">
								<FiUsers className="text-accent" />
								<span className="text-sm">{t("partner.invited", { defaultValue: "Приглашено" })}</span>
							</div>
							<div className="text-3xl font-bold text-foreground">{invited.toLocaleString()}</div>
						</div>
						<div className="rounded-2xl border border-border bg-surface p-6">
							<div className="flex items-center gap-2 text-muted mb-2">
								<FiTrendingUp className="text-accent" />
								<span className="text-sm">{t("partner.total_earned", { defaultValue: "Общий доход" })}</span>
							</div>
							<div className="text-3xl font-bold text-accent">
								{earned.toLocaleString()}{" "}
								<span className="text-base font-normal text-muted">
									{t("topup.credits", { defaultValue: "кредитов" })}
								</span>
							</div>
						</div>
					</section>
				)}

				{/* История начислений */}
				{authed && (
					<section className="py-2">
						<div className="rounded-2xl border border-border bg-surface p-6">
							<h2 className="text-lg font-semibold text-foreground mb-4">
								{t("partner.history_title", { defaultValue: "История начислений" })}
							</h2>
							{loading ? (
								<p className="text-muted text-sm">{t("common.loading", { defaultValue: "Загрузка..." })}</p>
							) : history.length === 0 ? (
								<p className="text-muted-2 text-sm italic">
									{t("partner.history_empty", {
										defaultValue: "Пока нет начислений. Приглашайте друзей — и они появятся здесь.",
									})}
								</p>
							) : (
								<div className="overflow-x-auto">
									<table className="w-full text-sm">
										<thead>
											<tr className="text-left text-muted-2 border-b border-border">
												<th className="py-2 pr-3 font-medium">{t("partner.col_date", { defaultValue: "Дата" })}</th>
												<th className="py-2 font-medium text-right">{t("partner.col_amount", { defaultValue: "Сумма" })}</th>
											</tr>
										</thead>
										<tbody>
											{history.map((row, i) => (
												<tr key={i} className="border-b border-border/50 last:border-0">
													<td className="py-2.5 pr-3 text-muted whitespace-nowrap">{formatDate(row.date)}</td>
													<td className="py-2.5 text-right font-semibold text-green-500 whitespace-nowrap">
														+{Number(row.amount ?? 0).toLocaleString()}
													</td>
												</tr>
											))}
										</tbody>
									</table>
								</div>
							)}
						</div>
					</section>
				)}

				{/* Как это работает */}
				<section className="py-6">
					<h2 className="text-2xl font-semibold text-center">
						{t("partner.how_title", { defaultValue: "Как это работает" })}
					</h2>

					<div className="grid md:grid-cols-3 grid-cols-1 gap-6 mt-6">
						<div className="rounded-xl border border-border p-5 bg-surface">
							<h3 className="font-semibold text-lg mb-2 text-foreground">
								{t("partner.step1.title", { defaultValue: "Поделитесь ссылкой" })}
							</h3>
							<p className="text-sm text-muted">
								{t("partner.step1.text", {
									defaultValue: "Отправьте вашу партнёрскую ссылку друзьям и в соцсети.",
								})}
							</p>
						</div>
						<div className="rounded-xl border border-border p-5 bg-surface">
							<h3 className="font-semibold text-lg mb-2 text-foreground">
								{t("partner.step2.title", { defaultValue: "Друзья пополняют баланс" })}
							</h3>
							<p className="text-sm text-muted">
								{t("partner.step2.text", {
									defaultValue: "Приглашённые регистрируются по ссылке и пополняют счёт.",
								})}
							</p>
						</div>
						<div className="rounded-xl border border-border p-5 bg-surface">
							<h3 className="font-semibold text-lg mb-2 text-foreground">
								{t("partner.step3.title", { defaultValue: "Вы получаете кредиты" })}
							</h3>
							<p className="text-sm text-muted">
								{t("partner.step3.text", {
									defaultValue:
										"С каждого пополнения приглашённых вам начисляется процент — пожизненно.",
								})}
							</p>
						</div>
					</div>
				</section>
			</div>
		</main>
	);
}
