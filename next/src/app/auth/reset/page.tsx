"use client";

import "@/assets/style.scss";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Field } from "@/components/ui/inputs/Inputs";
import { Alert } from "@/components/ui/alert/Alert";
import { fetchData } from "@/tools/fetchData";
import SmartForm from "@/components/forms/SmartForm";

export default function ResetPassword() {
	const { t } = useTranslation("common");
	const [step, setStep] = useState<"request" | "verify" | "reset">("request");
	const [email, setEmail] = useState("");
	const [code, setCode] = useState("");
	const [alert, setAlert] = useState<{ title: string; message: string; type: any } | null>(null);
	const show = (title: string, message: string, type: "success" | "error" | "info" | "warning") =>
		setAlert({ title, message, type });

	const onSubmit = async (data: any) => {
		if (step === "request") {
			const res = await fetchData("users/reset-password/request/", "POST", data).catch((e) => ({
				data: { status: "error", message: e.message },
			}));
			if (res?.data?.status === "success") {
				setEmail(data.email);
				setStep("verify");
				show(t("status.success"), t("auth.code_sent"), "info");
			} else {
				show(t("status.error"), res?.data?.message || t("status_extended.error"), "error");
			}
		} else if (step === "verify") {
			const res = await fetchData("users/reset-password/verify/", "POST", { email, code: data.code }).catch(
				(e) => ({ data: { status: "error", message: e.message } })
			);
			if (res?.data?.status === "success") {
				setCode(data.code);
				setStep("reset");
				show(t("status.success"), t("auth.code_verified"), "success");
			} else {
				show(t("status.error"), res?.data?.message || t("auth.invalid_code"), "error");
			}
		} else if (step === "reset") {
			const res = await fetchData("users/reset-password/complete/", "POST", {
				email,
				code,
				password: data.password,
			}).catch((e) => ({ data: { status: "error", message: e.message } }));
			if (res?.data?.status === "success") {
				show(t("status.success"), t("auth.password_changed"), "success");
				setTimeout(() => (window.location.href = "/auth/signin"), 2000);
			} else {
				show(t("status.error"), res?.data?.message || t("auth.reset_failed"), "error");
			}
		}
	};

	return (
		<SmartForm
			onSubmit={onSubmit}
			submitLabel={
				step === "request"
					? t("auth.resetPassword")
					: step === "verify"
					? t("auth.confirm")
					: t("auth.save_password")
			}
			loadingLabel={t("status.loading")}
			className="flex-1 h-full flex flex-col gap-8 items-center p-10 overflow-auto w-full"
		>
			<Alert
				show={!!alert}
				title={alert?.title || ""}
				message={alert?.message || ""}
				type={alert?.type}
				onClose={() => setAlert(null)}
				autoClose
				autoCloseDuration={2500}
				position="top"
				closeButton
			/>
			<img src="/images/logo/base.svg" alt="Logo" className="max-w-[200px]" />
			{step === "request" && (
				<div className="w-full select-none flex flex-col">
					<label htmlFor="email" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.email")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="email"
						name="email"
						placeholder={t("auth.enter_email")}
						id="email"
					/>
				</div>
			)}
			{step === "verify" && (
				<div className="w-full select-none flex flex-col">
					<label htmlFor="code" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.enter_code")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="text"
						name="code"
						placeholder="123456"
						id="code"
					/>
				</div>
			)}
			{step === "reset" && (
				<div className="w-full select-none flex flex-col">
					<label htmlFor="password" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.new_password")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="password"
						name="password"
						placeholder={t("auth.enter_new_password")}
						id="password"
					/>
				</div>
			)}
		</SmartForm>
	);
}
