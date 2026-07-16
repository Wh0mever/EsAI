"use client";

import "@/assets/style.scss";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import Cookies from "js-cookie";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import TransferCredits from "@/components/cabinet/TransferCredits";

/**
 * /transfer — страница перевода кредитов между пользователями.
 * Форма перевода + история (получено/отправлено). Гостю показываем предложение войти.
 */
export default function TransferPage() {
	const { t } = useTranslation("common");
	const [authed, setAuthed] = useState(false);
	const [ready, setReady] = useState(false);

	useEffect(() => {
		setAuthed(Boolean(Cookies.get("access")));
		setReady(true);
	}, []);

	return (
		<main className="mx-auto lg:pt-80 pt-50 pb-20 overflow-hidden relative">
			<Breadcrumb />

			<div className="mx-auto max-w-3xl px-4 py-5">
				<section className="py-8">
					<h1 className="text-3xl font-bold text-center">
						{t("transfer.title", { defaultValue: "Перевести кредиты" })}
					</h1>
					<p className="text-center text-muted text-base mt-4">
						{t("transfer.subtitle", {
							defaultValue: "Делитесь кредитами с другими пользователями EsAI.",
						})}
					</p>
				</section>

				{!ready ? null : authed ? (
					<TransferCredits />
				) : (
					<div className="rounded-2xl border border-border bg-surface p-6 text-center">
						<p className="text-muted text-sm mb-4">
							{t("transfer.guest_hint", { defaultValue: "Войдите, чтобы переводить кредиты." })}
						</p>
						<Link
							href="/auth/signin?next=%2Ftransfer"
							className="inline-flex items-center justify-center px-5 py-2.5 rounded-xl bg-accent text-on-accent font-semibold text-sm hover:bg-accent-strong transition-colors"
						>
							{t("auth.login", { defaultValue: "Войти" })}
						</Link>
					</div>
				)}
			</div>
		</main>
	);
}
