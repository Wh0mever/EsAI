"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiTag } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { getInvite } from "@/lib/creators/api";
import { promoCreatorAccepted, promoCreatorError } from "@/lib/creators/errors";

/**
 * Ответ users/promo/activate/. kind отличает код креатора (EsAI Creators) от
 * обычного промокода: код креатора ничего не начисляет, а закрепляет
 * человека за креатором.
 */
type PromoResult = {
	ok?: boolean;
	credited?: number;
	balance?: number;
	message?: string;
	detail?: string;
	kind?: "promo" | "creator";
	/** Причина отказа по коду креатора (self, too_late…) — по ней переводим текст. */
	code?: string;
};

type Props = {
	/** Уведомить родителя о новом балансе (например обновить карточку баланса). */
	onCredited?: (balance: number) => void;
	/** Без внешней карточки (border/bg/padding) — например внутри модалки. */
	bare?: boolean;
};

/**
 * PromoActivate — поле ввода промокода + кнопка «Активировать».
 * POST users/promo/activate/ { code } → { ok, credited, balance, message, kind }
 * | 400 { status: "error", message, kind?, code? }.
 * Обычный промокод: «Начислено N кредитов», ошибка — текст бэка.
 * Код креатора: ничего не начислено — «Промокод принят — вы пришли по
 * приглашению …»; отказ переводится по коду (текст бэка только русский).
 */
export default function PromoActivate({ onCredited, bare = false }: Props) {
	// creators — ленивый namespace: пока он грузится, работают русские тексты по умолчанию.
	const { t } = useTranslation(["common", "creators"], { useSuspense: false });
	const [code, setCode] = useState("");
	const [busy, setBusy] = useState(false);
	const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

	const submit = async (e?: React.FormEvent) => {
		e?.preventDefault();
		const value = code.trim();
		if (!value || busy) return;
		setBusy(true);
		setMsg(null);
		try {
			const res = await fetchData<PromoResult>("users/promo/activate/", "POST", { code: value }, true);
			const data: PromoResult = res.data && typeof res.data === "object" ? res.data : {};
			if (res.ok && data.ok && data.kind === "creator") {
				// Код креатора: кредитов нет, «Начислено 0» не пишем и баланс не трогаем.
				let text = data.message || "";
				const invite = await getInvite();
				if (invite.ok && invite.data.invited_by) text = promoCreatorAccepted(t, invite.data.invited_by);
				setMsg(text ? { type: "success", text } : null);
				setCode("");
			} else if (res.ok && data.ok) {
				const credited = Number(data.credited ?? 0);
				setMsg({
					type: "success",
					text: t("promo.credited", {
						defaultValue: "Начислено {{count}} кредитов",
						count: credited,
					}),
				});
				setCode("");
				if (typeof data.balance === "number") onCredited?.(data.balance);
			} else {
				const fallback =
					data.detail || res.error || t("promo.error", { defaultValue: "Не удалось активировать промокод." });
				setMsg({
					type: "error",
					text: data.kind === "creator" ? promoCreatorError(t, data.code, fallback) : fallback,
				});
			}
		} catch {
			setMsg({ type: "error", text: t("promo.error", { defaultValue: "Не удалось активировать промокод." }) });
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className={bare ? "" : "rounded-2xl border border-border bg-surface p-6"}>
			{!bare && (
				<div className="flex items-center gap-2 mb-3">
					<FiTag className="text-accent" />
					<h2 className="text-xl font-bold text-foreground">
						{t("promo.title", { defaultValue: "Активировать промокод" })}
					</h2>
				</div>
			)}
			<p className="text-muted text-sm mb-4">
				{t("promo.hint", { defaultValue: "Введите промокод, чтобы получить бонусные кредиты на баланс." })}
			</p>

			<form onSubmit={submit} className="flex flex-col sm:flex-row items-stretch gap-3">
				<input
					type="text"
					value={code}
					onChange={(e) => setCode(e.target.value)}
					placeholder={t("promo.placeholder", { defaultValue: "Промокод" })}
					className="flex-1 min-w-0 rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground placeholder:text-muted-2 focus:border-accent focus:outline-none transition-colors uppercase"
					aria-label={t("promo.title", { defaultValue: "Активировать промокод" })}
				/>
				<button
					type="submit"
					disabled={busy || !code.trim()}
					className="inline-flex items-center justify-center rounded-xl bg-accent text-on-accent font-semibold text-sm px-5 py-2.5 hover:bg-accent-strong transition-colors cursor-pointer shrink-0 disabled:opacity-60 disabled:cursor-default"
				>
					{busy
						? t("common.processing", { defaultValue: "Обработка..." })
						: t("promo.activate", { defaultValue: "Активировать" })}
				</button>
			</form>

			{msg && (
				<p className={`mt-3 text-sm ${msg.type === "success" ? "text-green-500" : "text-rose-400"}`}>
					{msg.text}
				</p>
			)}
		</div>
	);
}
