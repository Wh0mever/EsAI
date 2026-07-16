"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiSend, FiArrowDownLeft, FiArrowUpRight } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

type TransferRow = {
	date: string;
	direction: "in" | "out" | string;
	amount: number;
	counterparty: string;
	comment?: string;
};

function formatDate(raw?: string): string {
	if (!raw) return "";
	const d = new Date(raw);
	if (Number.isNaN(d.getTime())) return raw;
	return d.toLocaleString();
}

/**
 * TransferCredits — перевод кредитов другому пользователю + история переводов.
 * POST users/transfer/ { recipient, amount, comment } → { ok, balance }
 * GET  users/transfers/ → [{ date, direction, amount, counterparty, comment }]
 */
export default function TransferCredits({ onBalance }: { onBalance?: (balance: number) => void }) {
	const { t } = useTranslation("common");

	const [recipient, setRecipient] = useState("");
	const [amount, setAmount] = useState("");
	const [comment, setComment] = useState("");
	const [busy, setBusy] = useState(false);
	const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

	const [history, setHistory] = useState<TransferRow[]>([]);
	const [loadingHistory, setLoadingHistory] = useState(false);

	const loadHistory = async () => {
		setLoadingHistory(true);
		try {
			const res = await fetchData<TransferRow[]>("users/transfers/", "GET", null, true);
			setHistory(Array.isArray(res.data) ? res.data : []);
		} finally {
			setLoadingHistory(false);
		}
	};

	useEffect(() => {
		let mounted = true;
		(async () => {
			setLoadingHistory(true);
			try {
				const res = await fetchData<TransferRow[]>("users/transfers/", "GET", null, true);
				if (mounted) setHistory(Array.isArray(res.data) ? res.data : []);
			} finally {
				if (mounted) setLoadingHistory(false);
			}
		})();
		return () => {
			mounted = false;
		};
	}, []);

	const submit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (busy) return;
		const to = recipient.trim();
		const amt = Number(amount);
		if (!to || !Number.isFinite(amt) || amt <= 0) {
			setMsg({ type: "error", text: t("transfer.invalid", { defaultValue: "Укажите получателя и сумму больше нуля." }) });
			return;
		}
		setBusy(true);
		setMsg(null);
		try {
			const res = await fetchData<{ ok?: boolean; balance?: number; detail?: string }>(
				"users/transfer/",
				"POST",
				{ recipient: to, amount: amt, comment: comment.trim() },
				true
			);
			const data = res.data as any;
			if (res.ok && data?.ok) {
				const newBalance = Number(data.balance ?? 0);
				setMsg({
					type: "success",
					text: t("transfer.success", {
						defaultValue: "Переведено. Новый баланс: {{balance}} кредитов",
						balance: newBalance.toLocaleString(),
					}),
				});
				setRecipient("");
				setAmount("");
				setComment("");
				if (typeof data.balance === "number") onBalance?.(newBalance);
				loadHistory();
			} else {
				setMsg({
					type: "error",
					text: data?.detail || res.error || t("transfer.error", { defaultValue: "Не удалось выполнить перевод." }),
				});
			}
		} catch {
			setMsg({ type: "error", text: t("transfer.error", { defaultValue: "Не удалось выполнить перевод." }) });
		} finally {
			setBusy(false);
		}
	};

	const inputClass =
		"w-full rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground placeholder:text-muted-2 focus:border-accent focus:outline-none transition-colors";

	return (
		<div className="flex flex-col gap-4">
			{/* Форма перевода */}
			<div className="rounded-2xl border border-border bg-surface p-6">
				<div className="flex items-center gap-2 mb-3">
					<FiSend className="text-accent" />
					<h2 className="text-xl font-bold text-foreground">
						{t("transfer.title", { defaultValue: "Перевести кредиты" })}
					</h2>
				</div>
				<p className="text-muted text-sm mb-4">
					{t("transfer.hint", { defaultValue: "Отправьте кредиты другому пользователю — по email, логину или ID." })}
				</p>

				<form onSubmit={submit} className="flex flex-col gap-3">
					<div className="flex flex-col gap-1.5">
						<label htmlFor="transfer-recipient" className="text-sm text-muted">
							{t("transfer.recipient", { defaultValue: "Получатель (email / логин / ID)" })}
						</label>
						<input
							id="transfer-recipient"
							type="text"
							value={recipient}
							onChange={(e) => setRecipient(e.target.value)}
							placeholder={t("transfer.recipient_ph", { defaultValue: "user@example.com" })}
							className={inputClass}
						/>
					</div>

					<div className="flex flex-col gap-1.5">
						<label htmlFor="transfer-amount" className="text-sm text-muted">
							{t("transfer.amount", { defaultValue: "Сумма (кредитов)" })}
						</label>
						<input
							id="transfer-amount"
							type="number"
							min={1}
							step={1}
							inputMode="numeric"
							value={amount}
							onChange={(e) => setAmount(e.target.value)}
							placeholder="100"
							className={inputClass}
						/>
					</div>

					<div className="flex flex-col gap-1.5">
						<label htmlFor="transfer-comment" className="text-sm text-muted">
							{t("transfer.comment", { defaultValue: "Комментарий (необязательно)" })}
						</label>
						<input
							id="transfer-comment"
							type="text"
							value={comment}
							onChange={(e) => setComment(e.target.value)}
							placeholder={t("transfer.comment_ph", { defaultValue: "За помощь" })}
							className={inputClass}
						/>
					</div>

					<button
						type="submit"
						disabled={busy || !recipient.trim() || !amount.trim()}
						className="mt-1 inline-flex w-fit items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm px-6 py-2.5 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-default"
					>
						<FiSend />
						{busy
							? t("common.processing", { defaultValue: "Обработка..." })
							: t("transfer.submit", { defaultValue: "Перевести" })}
					</button>

					{msg && (
						<p className={`text-sm ${msg.type === "success" ? "text-green-500" : "text-rose-400"}`}>
							{msg.text}
						</p>
					)}
				</form>
			</div>

			{/* История переводов */}
			<div className="rounded-2xl border border-border bg-surface p-6">
				<h3 className="text-lg font-semibold text-foreground mb-4">
					{t("transfer.history_title", { defaultValue: "История переводов" })}
				</h3>

				{loadingHistory ? (
					<p className="text-muted text-sm">{t("common.loading", { defaultValue: "Загрузка..." })}</p>
				) : history.length === 0 ? (
					<p className="text-muted-2 text-sm italic">
						{t("transfer.history_empty", { defaultValue: "Переводов пока нет." })}
					</p>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full text-sm">
							<thead>
								<tr className="text-left text-muted-2 border-b border-border">
									<th className="py-2 pr-3 font-medium">{t("transfer.col_date", { defaultValue: "Дата" })}</th>
									<th className="py-2 pr-3 font-medium">{t("transfer.col_direction", { defaultValue: "Тип" })}</th>
									<th className="py-2 pr-3 font-medium">{t("transfer.col_counterparty", { defaultValue: "Контрагент" })}</th>
									<th className="py-2 pr-3 font-medium text-right">{t("transfer.col_amount", { defaultValue: "Сумма" })}</th>
									<th className="py-2 font-medium">{t("transfer.col_comment", { defaultValue: "Комментарий" })}</th>
								</tr>
							</thead>
							<tbody>
								{history.map((row, i) => {
									const incoming = row.direction === "in";
									return (
										<tr key={i} className="border-b border-border/50 last:border-0">
											<td className="py-2.5 pr-3 text-muted whitespace-nowrap">{formatDate(row.date)}</td>
											<td className="py-2.5 pr-3">
												<span
													className={`inline-flex items-center gap-1 ${
														incoming ? "text-green-500" : "text-rose-400"
													}`}
												>
													{incoming ? <FiArrowDownLeft /> : <FiArrowUpRight />}
													{incoming
														? t("transfer.received", { defaultValue: "Получено" })
														: t("transfer.sent", { defaultValue: "Отправлено" })}
												</span>
											</td>
											<td className="py-2.5 pr-3 text-foreground truncate max-w-[180px]">{row.counterparty}</td>
											<td
												className={`py-2.5 pr-3 text-right font-semibold whitespace-nowrap ${
													incoming ? "text-green-500" : "text-rose-400"
												}`}
											>
												{incoming ? "+" : "−"}
												{Number(row.amount ?? 0).toLocaleString()}
											</td>
											<td className="py-2.5 text-muted truncate max-w-[220px]">{row.comment || "—"}</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</div>
		</div>
	);
}
