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
 * GET  users/transfer/ → { transferable, balance } — сколько можно перевести
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
	// Перевод необратим: сначала показываем, кому и сколько уйдёт, и ждём
	// явного «Да». Раньше кредиты уходили по первому нажатию.
	const [confirm, setConfirm] = useState<{ to: string; amt: number } | null>(null);
	// Переводить можно только купленные кредиты — подарочные (ежедневные,
	// приветственные, промокоды) остаются у владельца. null — сервер не ответил,
	// тогда не ограничиваем на клиенте: последнее слово всё равно за бэкендом.
	const [transferable, setTransferable] = useState<number | null>(null);

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

	const loadTransferable = async () => {
		const res = await fetchData<{ transferable?: number }>("users/transfer/", "GET", null, true);
		if (res.ok && typeof res.data?.transferable === "number") setTransferable(res.data.transferable);
	};

	useEffect(() => {
		let mounted = true;
		(async () => {
			const res = await fetchData<{ transferable?: number }>("users/transfer/", "GET", null, true);
			if (mounted && res.ok && typeof res.data?.transferable === "number") {
				setTransferable(res.data.transferable);
			}
		})();
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

	// Шаг 1: проверяем поля и показываем подтверждение.
	const submit = (e: React.FormEvent) => {
		e.preventDefault();
		if (busy) return;
		const to = recipient.trim();
		const raw = amount.trim();
		if (!to || !raw) {
			setMsg({ type: "error", text: t("transfer.invalid", { defaultValue: "Укажите получателя и сумму больше нуля." }) });
			return;
		}
		// Только целые: бэкенд делает int(), и «1.5» молча превращалось в 1.
		if (!/^\d+$/.test(raw) || Number(raw) < 1) {
			setMsg({
				type: "error",
				text: t("transfer.invalid_integer", { defaultValue: "Сумма — целое число кредитов больше нуля, например 100." }),
			});
			return;
		}
		const amt = Number(raw);
		if (transferable !== null && amt > transferable) {
			setMsg({
				type: "error",
				text:
					transferable > 0
						? t("transfer.over_limit", {
								defaultValue: "Сейчас можно перевести не больше {{amount}} кр.",
								amount: transferable.toLocaleString(),
							})
						: t("transfer.nothing_to_transfer", {
								defaultValue: "Сейчас переводить нечего: на балансе только бонусные кредиты.",
							}),
			});
			return;
		}
		setMsg(null);
		setConfirm({ to, amt });
	};

	// Шаг 2: человек подтвердил — переводим.
	const doTransfer = async () => {
		if (busy || !confirm) return;
		const { to, amt } = confirm;
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
				loadTransferable();
			} else {
				// 400 с лимитом приносит актуальное «можно перевести» — обновляем подсказку.
				if (typeof data?.transferable === "number") setTransferable(data.transferable);
				setMsg({
					type: "error",
					text: data?.detail || res.error || t("transfer.error", { defaultValue: "Не удалось выполнить перевод." }),
				});
			}
		} catch {
			setMsg({ type: "error", text: t("transfer.error", { defaultValue: "Не удалось выполнить перевод." }) });
		} finally {
			setBusy(false);
			setConfirm(null);
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
							onChange={(e) => {
								setRecipient(e.target.value);
								setConfirm(null);
							}}
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
							max={transferable ?? undefined}
							inputMode="numeric"
							value={amount}
							onChange={(e) => {
								setAmount(e.target.value);
								setConfirm(null);
							}}
							placeholder="100"
							className={inputClass}
						/>
						{transferable !== null && (
							<p className="text-xs text-muted">
								<span className="font-semibold text-foreground">
									{t("transfer.transferable", {
										defaultValue: "Можно перевести: {{amount}} кр",
										amount: transferable.toLocaleString(),
									})}
								</span>
								{" · "}
								{t("transfer.transferable_hint", {
									defaultValue: "бонусные кредиты (ежедневные, приветственные, по промокодам) переводить нельзя.",
								})}
							</p>
						)}
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

					{confirm ? (
						<div className="mt-1 flex flex-col gap-3 rounded-xl border border-accent/50 bg-accent/5 p-4">
							<p className="text-sm text-foreground">
								{t("transfer.confirm_text", {
									defaultValue: "Перевести {{amount}} кр пользователю «{{recipient}}»? Отменить перевод будет нельзя.",
									amount: confirm.amt.toLocaleString(),
									recipient: confirm.to,
								})}
							</p>
							<div className="flex flex-wrap gap-2">
								<button
									type="button"
									onClick={doTransfer}
									disabled={busy}
									className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm px-5 py-2.5 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-default"
								>
									<FiSend />
									{busy
										? t("common.processing", { defaultValue: "Обработка..." })
										: t("transfer.confirm_yes", { defaultValue: "Да, перевести" })}
								</button>
								<button
									type="button"
									onClick={() => setConfirm(null)}
									disabled={busy}
									className="inline-flex items-center justify-center rounded-xl border border-border px-5 py-2.5 text-sm text-foreground hover:bg-surface-2 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-default"
								>
									{t("common.cancel", { defaultValue: "Отмена" })}
								</button>
							</div>
						</div>
					) : (
						<button
							type="submit"
							disabled={busy || !recipient.trim() || !amount.trim() || transferable === 0}
							className="mt-1 inline-flex w-fit items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm px-6 py-2.5 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-default"
						>
							<FiSend />
							{t("transfer.submit", { defaultValue: "Перевести" })}
						</button>
					)}

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
