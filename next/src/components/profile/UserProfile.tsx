"use client";

import React, { useEffect, useState, useRef } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { Field, Checkbox } from "@/components/ui/inputs/Inputs";
import { PiUserLight } from "react-icons/pi";
import { fetchData } from "@/tools/fetchData";
import { ConfirmationModal, Modal } from "@/components/dialog/Dialog";
import Cookies from "js-cookie";
import { Alert } from "@/components/ui/alert/Alert";

async function changeUserInfo(data: any): Promise<Number> {
	let status = 400;

	await fetchData("users/profile/", "put", data, true).then((response) => {
		if (response) {
			status = response.status;
		}
	});
	return status;
}

function formatNotificationDate(raw?: string | null): string {
	if (!raw) return "";
	const d = new Date(raw);
	if (Number.isNaN(d.getTime())) return "";
	return d.toLocaleString();
}

export default function UserProfile({ t, data }: { t: any; data: any }) {
	const [userData, setUserData] = useState({});
	const [userChange, setUserChange] = useState<any>({
		show: false,
		text: "",
		type: "",
		_2fa: data?.user?._2fa,
	});

	const [isLogoutConfirmModalOpen, setLogoutConfirmModalOpen] = useState(false);
	const [notifOpen, setNotifOpen] = useState(false);
	const [notifList, setNotifList] = useState<any[]>([]);
	const [notifLoading, setNotifLoading] = useState(false);
	const [selectedNotif, setSelectedNotif] = useState<any | null>(null);
	const [unreadCount, setUnreadCount] = useState<number>(0);
	const dropdownRef = useRef<HTMLDivElement | null>(null);

	// Feedback modal state
	const [feedbackOpen, setFeedbackOpen] = useState(false);
	const [feedbackRating, setFeedbackRating] = useState<number | null>(5);
	const [feedbackText, setFeedbackText] = useState("");
	const [feedbackSending, setFeedbackSending] = useState(false);
	const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);

	// Floating alert for feedback result
	const [alertOpen, setAlertOpen] = useState(false);
	const [alertTitle, setAlertTitle] = useState("");
	const [alertMessage, setAlertMessage] = useState("");
	const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("success");

	useEffect(() => {
		if (!notifOpen) return;
		let ignore = false;
		(async () => {
			try {
				setNotifLoading(true);
				const res = await fetchData("users/notifications/", "GET", null, true);
				if (!ignore) {
					const list = Array.isArray(res?.data) ? res.data : [];
					setNotifList(list);
					setUnreadCount(list.filter((n: any) => !n.is_read).length);
				}
			} catch {
				if (!ignore) setNotifList([]);
			} finally {
				if (!ignore) setNotifLoading(false);
			}
		})();
		return () => {
			ignore = true;
		};
	}, [notifOpen]);

	// initial unread counter on mount
	useEffect(() => {
		let ignore = false;
		(async () => {
			try {
				const res = await fetchData("users/notifications/?unread=1", "GET", null, true);
				if (!ignore) setUnreadCount(Array.isArray(res?.data) ? res.data.length : 0);
			} catch {
				if (!ignore) setUnreadCount(0);
			}
		})();
		const onUpd = async () => {
			try {
				const res = await fetchData("users/notifications/?unread=1", "GET", null, true);
				setUnreadCount(Array.isArray(res?.data) ? res.data.length : 0);
			} catch {
				setUnreadCount(0);
			}
		};
		window.addEventListener("notifications:updated", onUpd);
		return () => {
			ignore = true;
			window.removeEventListener("notifications:updated", onUpd);
		};
	}, []);

	// close dropdown on outside click
	useEffect(() => {
		if (!notifOpen) return;
		const onDoc = (e: MouseEvent) => {
			const el = dropdownRef.current;
			if (!el) return;
			if (!el.contains(e.target as Node)) setNotifOpen(false);
		};
		document.addEventListener("mousedown", onDoc);
		return () => document.removeEventListener("mousedown", onDoc);
	}, [notifOpen]);

	const openNotif = async (n: any) => {
		setSelectedNotif(n);
		// optimistic: mark as read locally immediately
		if (!n?.is_read && n?.delivery_id) {
			setNotifList((prev) =>
				prev.map((x) =>
					x.delivery_id === n.delivery_id ? { ...x, is_read: true, read_at: new Date().toISOString() } : x
				)
			);
			setUnreadCount((c) => Math.max(0, c - 1));
			try {
				await fetchData(`users/notifications/${n.delivery_id}/read/`, "PATCH", {}, true);
				// signal others (e.g., sidebar) to refresh counters
				try {
					window.dispatchEvent(new CustomEvent("notifications:updated"));
				} catch {}
			} catch {
				// revert if failed
				setNotifList((prev) =>
					prev.map((x) => (x.delivery_id === n.delivery_id ? { ...x, is_read: false, read_at: null } : x))
				);
				setUnreadCount((c) => c + 1);
			}
		}
	};

	useEffect(() => {
		if (userChange.show) {
			setTimeout(() => {
				setUserChange(() => {
					return {
						...userChange,
						show: false,
					};
				});
			}, 3000);
		}
	}, [userChange, setUserChange]);

	function handleLogout() {
		Cookies.remove("access");
		Cookies.remove("refresh");
		Cookies.remove("user");
		Cookies.remove("sessionid");
		window.location.href = "/auth/signin";
	}

	return (
		<>
		<Card>
			<div className="flex-grow flex flex-col gap-3">
				<div className="flex flex-col gap-2">
					<div className="flex justify-between items-center relative">
						<h2 className="text-xl font-bold">{t("profile.profile")} </h2>
						<div className="flex items-center gap-2">
							<i className="text-7xl text-muted">
								<PiUserLight />
							</i>
						</div>
					</div>
					{userChange.show && (
						<div
							className={`${userChange.type === "warning" && "text-amber-400"} ${
								userChange.type === "success" && "text-green-600"
							}`}
						>
							{userChange.text}
						</div>
					)}
				</div>
				
				{/* Notifications dropdown button */}
		<div className="relative pb-5" ref={dropdownRef}>
					<button
						type="button"
						className="px-3 py-1.5 cursor-pointer rounded-md bg-surface-2 hover:bg-surface-3 text-sm border border-border relative"
						onClick={() => setNotifOpen((v) => !v)}
					>
						{t("common.notifications")}
						{unreadCount > 0 && (
							<span className="absolute -top-2 -right-2 bg-rose-600 text-white text-xs font-medium rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
								{unreadCount}
							</span>
						)}
					</button>
					{/* Feedback button next to notifications */}
					<button
						type="button"
						className="ml-2 px-3 py-1.5 cursor-pointer rounded-md bg-surface-2 hover:bg-surface-3 text-sm border border-border"
						onClick={() => setFeedbackOpen(true)}
					>
						{t("profile.leave_feedback")}
					</button>
            {notifOpen && (
                <div className="absolute left-0 mt-2 w-72 max-h-[450px] overflow-auto bg-surface border border-border rounded-lg shadow-lg z-50">
                    <div className="p-2 border-b border-border text-sm text-muted">
                        {t("common.notifications")}
                    </div>
							{notifLoading ? (
								<div className="p-3 text-sm text-muted">{t("common.loading")}</div>
							) : notifList.length === 0 ? (
								<div className="p-3 text-sm text-muted">{t("status.notfound")}</div>
							) : (
								<ul className="py-1">
									{notifList.map((n) => (
										<li key={`${n.delivery_id}-${n.id}`}>
											<button
												className={`w-full cursor-pointer text-left px-3 py-2 text-sm hover:bg-surface-2 flex items-center gap-2 ${
													n.is_read ? "text-muted" : "text-foreground"
												}`}
												onClick={() => openNotif(n)}
											>
												{!n.is_read && (
													<span className="inline-block w-2 h-2 rounded-full bg-rose-500" />
												)}
												<span className="min-w-0">
													<span className="block truncate">{n.title}</span>
													<span className="block text-[11px] text-muted-2 mt-0.5">
														{formatNotificationDate(n.created_at)}
													</span>
												</span>
											</button>
										</li>
									))}
								</ul>
							)}
						</div>
					)}
				</div>
				
				<div className="flex flex-col gap-1">
					<p className="text-muted">{t("profile.email")}:</p>
					<Field
						name="email"
						className="border-b rounded-none border-border-strong flex-grow text-muted"
						value={data?.user?.email}
						disabled
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-muted">{t("profile.fullname")}:</p>
					<Field
						name="first_name"
						className="border-b rounded-none border-border-strong flex-grow"
						value={data?.user?.first_name}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									first_name: e.target.value,
								};
							});
						}}
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-muted">{t("profile.phone")}:</p>
					<Field
						name="tel"
						className="border-b rounded-none border-border-strong flex-grow"
						value={data?.user?.tel}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									tel: e.target.value,
								};
							});
						}}
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-muted">{t("profile._2fa")}:</p>
					<Checkbox
						name="_2fa"
						className="border-b rounded-none border-border-strong flex-grow"
						checked={data?.user?._2fa}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									_2fa: e.target.checked,
								};
							});
						}}
					/>
				</div>

				<div className="flex gap-3 items-center mt-5">
					<Button
						className="px-6 py-2 rounded-xl bg-accent text-on-accent hover:bg-accent-strong w-fit"
						onClick={() => {
							if (Object.keys(userData).length) {
								const responseStatus = changeUserInfo(userData).then((status) => {
									if (status === 200) {
										setUserChange({
											show: true,
											text: t("profile.user_info.user_changed"),
											type: "success",
										});
									}
								});
							} else {
								setUserChange({
									show: true,
									text: t("profile.user_info.no_data"),
									type: "warning",
								});
							}
						}}
					>
						{t("profile.change")}
					</Button>

					<Button
						className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700"
						onClick={() => setLogoutConfirmModalOpen(true)}
					>
						{t("nav.logout")}
					</Button>
				</div>
			</div>
			{/* Logout confirmation modal */}
			<ConfirmationModal
				isOpen={isLogoutConfirmModalOpen}
				title={t("nav.logOutConfirmTitle")}
				confirmText={t("common.yes")}
				cancelText={t("common.no")}
				onConfirm={handleLogout}
				onCancel={() => setLogoutConfirmModalOpen(false)}
			/>

			{/* Notification view modal */}
			<Modal
				title={selectedNotif?.title || t("common.notifications")}
				open={!!selectedNotif}
				onClose={() => setSelectedNotif(null)}
				size="md"
			>
				<div className="space-y-2">
					<div className="text-xs text-muted">
						{formatNotificationDate(selectedNotif?.created_at)}
					</div>
					<div className="text-foreground whitespace-pre-wrap leading-relaxed">{selectedNotif?.body || ""}</div>
				</div>
			</Modal>

			{/* Feedback modal */}
			<Modal
				title={t("profile.leave_feedback")}
				open={feedbackOpen}
				onClose={() => {
					if (!feedbackSending) setFeedbackOpen(false);
				}}
				size="md"
			>
				<div className="space-y-3">
					<label className="block text-sm text-muted">
						{t("profile.feedback_rating")}
						<select
							className="mt-1 w-full bg-surface-2 border border-border rounded-md p-2"
							value={feedbackRating ?? ''}
							onChange={(e) => setFeedbackRating(e.target.value ? Number(e.target.value) : null)}
						>
							<option value="">—</option>
							{[5,4,3,2,1].map((n) => (
								<option key={n} value={n}>{n} ★</option>
							))}
						</select>
					</label>
					<label className="block text-sm text-muted">
						{t("profile.feedback_placeholder")}
						<textarea
							className="mt-1 w-full bg-surface-2 border border-border rounded-md p-2 min-h-[120px]"
							value={feedbackText}
							onChange={(e) => setFeedbackText(e.target.value)}
						/>
					</label>
					{feedbackMessage && (
						<div className="text-sm text-muted">{feedbackMessage}</div>
					)}
					<div className="flex justify-end gap-2 pt-2">
						<Button
							className="px-4 py-2 rounded-md bg-surface-2 hover:bg-surface-3"
							onClick={() => !feedbackSending && setFeedbackOpen(false)}
						>
							{t("common.cancel")}
						</Button>
						<Button
							className="px-4 py-2 rounded-md bg-accent text-on-accent hover:bg-accent-strong disabled:opacity-50"
							disabled={feedbackSending || !feedbackText.trim()}
							onClick={async () => {
								try {
									setFeedbackSending(true);
									setFeedbackMessage(null);
									const payload: any = { message: feedbackText.trim() };
									if (feedbackRating) payload.rating = feedbackRating;
									const res = await fetchData("users/feedback/", "POST", payload, true);
									if (res?.ok) {
										setFeedbackMessage(t("profile.feedback_sent"));
										// Show translated success alert
										setAlertType("success");
										setAlertTitle(t("status_extended.success"));
										setAlertMessage(t("profile.feedback_sent"));
										setAlertOpen(true);
										setFeedbackText("");
										setFeedbackRating(5);
										setTimeout(() => setFeedbackOpen(false), 800);
									} else {
										setFeedbackMessage(res?.error || t("status_extended.error"));
									}
								} finally {
									setFeedbackSending(false);
								}
							}}
						>
							{feedbackSending ? t("common.processing") : t("profile.feedback_send")}
						</Button>
					</div>
				</div>
			</Modal>
		</Card>
		{/* Global alert shown after feedback submission */}
		<Alert
			show={alertOpen}
			onClose={() => setAlertOpen(false)}
			type={alertType}
			title={alertTitle}
			message={alertMessage}
			position="top"
			autoClose={true}
			autoCloseDuration={3000}
		/>
		</>
	);
}
