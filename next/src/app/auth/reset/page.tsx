"use client";

import "@/assets/style.scss";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Field } from "@/components/ui/inputs/Inputs";
import { Alert } from "@/components/ui/alert/Alert";
import { fetchData } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import SmartForm from "@/components/forms/SmartForm";

const INPUT_CLASS =
	"w-full rounded-xl bg-surface-2 border border-border text-foreground placeholder:text-muted-2 text-sm px-4 py-3 focus:border-accent focus:outline-none transition-colors";

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
		<div className="w-full flex flex-col gap-7">
			{alert && (
				<Alert
					show
					title={alert.title}
					message={alert.message}
					type={alert.type}
					onClose={() => setAlert(null)}
					position="top"
					offset={20}
					autoClose
					autoCloseDuration={2500}
					closeButton
				/>
			)}

			<NextLink href="/" className="lg:hidden flex justify-center">
				<img src="/esai-logo.svg" alt="EsAI" className="h-8" />
			</NextLink>

			<div className="text-center space-y-1">
				<h1 className="text-2xl font-bold text-foreground">{t("auth.resetPassword", { defaultValue: "Восстановление пароля" })}</h1>
				<p className="text-sm text-muted">
					{step === "request"
						? t("auth.reset_hint", { defaultValue: "Введите email — пришлём код" })
						: step === "verify"
						? t("auth.enter_code", { defaultValue: "Введите код из письма" })
						: t("auth.new_password", { defaultValue: "Новый пароль" })}
				</p>
			</div>

			<SmartForm
				onSubmit={onSubmit}
				submitLabel={
					step === "request" ? t("auth.resetPassword") : step === "verify" ? t("auth.confirm") : t("auth.save_password")
				}
				loadingLabel={t("status.loading")}
				className="w-full flex flex-col gap-4"
			>
				{step === "request" && (
					<div className="flex flex-col gap-1.5">
						<label htmlFor="email" className="text-sm text-muted">{t("auth.email")} <span className="text-accent">*</span></label>
						<Field className={INPUT_CLASS} type="email" name="email" placeholder={t("auth.enter_email")} id="email" />
					</div>
				)}
				{step === "verify" && (
					<div className="flex flex-col gap-1.5">
						<label htmlFor="code" className="text-sm text-muted">{t("auth.enter_code")} <span className="text-accent">*</span></label>
						<Field className={`${INPUT_CLASS} tracking-[0.4em] text-center`} type="text" name="code" placeholder="XXXXXX" id="code" />
					</div>
				)}
				{step === "reset" && (
					<div className="flex flex-col gap-1.5">
						<label htmlFor="password" className="text-sm text-muted">{t("auth.new_password")} <span className="text-accent">*</span></label>
						<Field className={INPUT_CLASS} type="password" name="password" placeholder={t("auth.enter_new_password")} id="password" />
					</div>
				)}
			</SmartForm>

			<div className="text-center text-sm">
				<NextLink href="/auth/signin" className="text-accent font-medium hover:underline">{t("auth.signin", { defaultValue: "Войти" })}</NextLink>
			</div>
		</div>
	);
}
