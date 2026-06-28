"use client";

import "@/assets/style.scss";
import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert } from "@/components/ui/alert/Alert";
import { Field } from "@/components/ui/inputs/Inputs";
import NextLink from "@/components/ui/nextLink/NextLink";
import { fetchData } from "@/tools/fetchData";
import SmartForm from "@/components/forms/SmartForm";
import SocialAuthButtons from "@/components/auth/SocialAuthButtons";

type ApiOk = { status: "success"; title?: string; message?: string };
type ApiErr = { status: "error"; title?: string; message?: string; errors?: Record<string, string[] | string> };
type ApiPayload = ApiOk | ApiErr | any;

const INPUT_CLASS =
	"w-full rounded-xl bg-surface-2 border border-border text-foreground placeholder:text-muted-2 text-sm px-4 py-3 focus:border-accent focus:outline-none transition-colors";

export default function SignUp() {
	const { t } = useTranslation("common");
	const [responseData, setResponseData] = useState<ApiPayload | null>(null);
	const [showAlert, setShowAlert] = useState(false);
	const [alertTitle, setAlertTitle] = useState("Успешно");
	const [alertMessage, setAlertMessage] = useState("");
	const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");

	const formatErrors = (errors?: ApiErr["errors"]) => {
		if (!errors) return "";
		if (typeof errors === "string") return errors;
		const lines: string[] = [];
		for (const [field, msgs] of Object.entries(errors)) {
			const text = Array.isArray(msgs) ? msgs.join("; ") : msgs;
			lines.push(`${field}: ${text}`);
		}
		return lines.join("\n");
	};

	const autoClose = useMemo(() => alertType !== "error", [alertType]);

	useEffect(() => {
		if (!responseData) return;
		if (responseData.status === "success") {
			setShowAlert(true);
			setAlertType("success");
			setAlertTitle(responseData.title || t("status.success"));
			setAlertMessage(responseData.message || t("status_extended.success"));
			const id = setTimeout(() => {
				window.location.href = "/auth/signin";
			}, 2000);
			return () => clearTimeout(id);
		} else {
			const msg = responseData.message || formatErrors((responseData as ApiErr).errors) || t("status_extended.error");
			setShowAlert(true);
			setAlertType("error");
			setAlertTitle(responseData.title || t("status.error"));
			setAlertMessage(msg);
		}
	}, [responseData, t]);

	const onSubmit = async (data: any) => {
		const res = await fetchData<ApiPayload>("users/signup/", "POST", data, false);
		const payload = res?.data ?? { status: res.ok ? "success" : "error", message: res.error };
		setResponseData(payload);
	};

	return (
		<div className="w-full flex flex-col gap-6">
			<Alert
				show={showAlert}
				title={alertTitle}
				message={alertMessage}
				type={alertType}
				onClose={() => setShowAlert(false)}
				position="top"
				offset={20}
				autoClose={autoClose}
				autoCloseDuration={2000}
				closeButton
			/>

			<NextLink href="/" className="lg:hidden flex justify-center">
				<img src="/esai-logo.svg" alt="EsAI" className="h-8" />
			</NextLink>

			<div className="text-center space-y-1">
				<h1 className="text-2xl font-bold text-foreground">{t("auth.title", { defaultValue: "Регистрация в EsAI" })}</h1>
				<p className="text-sm text-muted">{t("auth.subtitle", { defaultValue: "Все AI в одном месте" })}</p>
			</div>

			<SocialAuthButtons />

			<div className="relative flex items-center justify-center">
				<span className="w-full border-t border-border" />
				<span className="absolute px-3 text-xs uppercase tracking-wide text-muted-2 bg-background">
					{t("auth.or", { defaultValue: "или" })}
				</span>
			</div>

			<SmartForm
				onSubmit={onSubmit}
				submitLabel={t("auth.signup")}
				loadingLabel={t("status.loading")}
				className="w-full flex flex-col gap-4"
			>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="name" className="text-sm text-muted">{t("auth.fullname")} <span className="text-accent">*</span></label>
					<Field className={INPUT_CLASS} type="text" name="name" placeholder={t("auth.enter_fullname")} id="name" />
				</div>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="email" className="text-sm text-muted">{t("auth.email")} <span className="text-accent">*</span></label>
					<Field className={INPUT_CLASS} type="email" name="email" placeholder={t("auth.enter_email")} id="email" />
				</div>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="tel" className="text-sm text-muted">{t("auth.tel")} <span className="text-accent">*</span></label>
					<Field className={INPUT_CLASS} type="tel" name="tel" placeholder="+996 xxx xxx xxx" id="tel" />
				</div>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="referral_uid" className="text-sm text-muted">{t("auth.referral_code")}</label>
					<Field className={INPUT_CLASS} type="text" name="referral_uid" placeholder={t("auth.enter_referral_code")} id="referral_uid" />
				</div>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="password" className="text-sm text-muted">{t("auth.password")} <span className="text-accent">*</span></label>
					<Field className={INPUT_CLASS} type="password" name="password" placeholder={t("auth.enter_password")} id="password" />
				</div>
				<div className="flex flex-col gap-1.5">
					<label htmlFor="password_repeat" className="text-sm text-muted">{t("auth.confirm_password")} <span className="text-accent">*</span></label>
					<Field className={INPUT_CLASS} type="password" name="password_repeat" placeholder={t("auth.confirm_password")} id="password_repeat" />
				</div>
			</SmartForm>

			<div className="text-center flex items-center justify-center gap-2 text-sm">
				<span className="text-muted">{t("auth.have_account")}</span>
				<NextLink href="/auth/signin" className="text-accent font-medium hover:underline">{t("auth.signin")}</NextLink>
			</div>
		</div>
	);
}
