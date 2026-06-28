"use client";

import "@/assets/style.scss";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { Alert } from "@/components/ui/alert/Alert";
import { Field } from "@/components/ui/inputs/Inputs";
import NextLink from "@/components/ui/nextLink/NextLink";
import { fetchData } from "@/tools/fetchData";
import SmartForm from "@/components/forms/SmartForm";
import SocialAuthButtons from "@/components/auth/SocialAuthButtons";

const INPUT_CLASS =
	"w-full rounded-xl bg-surface-2 border border-border text-foreground placeholder:text-muted-2 text-sm px-4 py-3 focus:border-accent focus:outline-none transition-colors";

function signin(response: any, setResponseData: any, t: any) {
	const { access, refresh, user } = response.data.data;

	Cookies.remove("access");
	Cookies.remove("refresh");
	Cookies.remove("user");
	Cookies.remove("sessionid");

	Cookies.set("access", access, { expires: 7 });
	Cookies.set("refresh", refresh, { expires: 15 });
	Cookies.set("user", JSON.stringify(user));

	setResponseData({
		status: "success",
		title: t("status.success"),
		message: t("status_extended.success"),
	});
}

export default function SignIn() {
	const { t } = useTranslation("common");
	const [step, setStep] = useState<"signin" | "verify">("signin");
	const [formState, setFormState] = useState<{ email?: string }>({});
	const [responseData, setResponseData] = useState<any>(null);
	const [showAlert, setShowAlert] = useState(false);
	const [alertTitle, setAlertTitle] = useState(t("status.success"));
	const [alertMessage, setAlertMessage] = useState("");
	const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");

	useEffect(() => {
		if (responseData) {
			setShowAlert(true);
			setAlertTitle(responseData.title || t("status.success"));
			setAlertMessage(responseData.message || t("status_extended.success"));
			setAlertType(responseData.status || "warning");
			if (responseData.status === "success") {
				setTimeout(() => {
					window.location.href = "/dashboard/text-chat";
				}, 1500);
			}
		}
	}, [responseData, t]);

	const onSubmit = async (data: any) => {
		if (step === "signin") {
			const email = data.email;
			setFormState({ email });
			const response = await fetchData("users/signin/", "POST", data).catch((error) => ({
				data: { status: "error", message: error.message },
			}));
			if (response?.data?.status === "success") {
				setStep("verify");
				setResponseData({
					status: "info",
					title: t("status.code_sent"),
					message: t("status_extended.check_email"),
				});
			} else if (response?.data?.status === "authenticated") {
				signin(response, setResponseData, t);
			} else {
				setResponseData({
					status: "error",
					title: t("status.error"),
					message: response?.data?.message || t("status_extended.error_username_password"),
				});
			}
		}
		if (step === "verify") {
			const response = await fetchData("users/signin/confirm/", "POST", {
				email: formState.email,
				code: data.code,
			}).catch((error) => ({ data: { status: "error", message: error.message } }));
			if (response?.data?.status === "authenticated") {
				signin(response, setResponseData, t);
			} else {
				setResponseData({
					status: "error",
					title: t("status.error"),
					message: response?.data?.message || t("status_extended.invalid_code"),
				});
			}
		}
	};

	return (
		<div className="w-full flex flex-col gap-7">
			<Alert
				show={showAlert}
				title={alertTitle}
				message={alertMessage}
				type={alertType}
				onClose={() => setShowAlert(false)}
				position="top"
				offset={20}
				autoClose
				autoCloseDuration={2000}
				closeButton
			/>

			{/* Лого только на мобиле (на десктопе оно в левой панели) */}
			<NextLink href="/" className="lg:hidden flex justify-center">
				<img src="/esai-logo.svg" alt="EsAI" className="h-8" />
			</NextLink>

			<div className="text-center space-y-1">
				<h1 className="text-2xl font-bold text-foreground">{t("auth.title", { defaultValue: "Вход в EsAI" })}</h1>
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
				submitLabel={step === "signin" ? t("auth.signin") : t("auth.confirm")}
				loadingLabel={t("status.loading")}
				className="w-full flex flex-col gap-4"
			>
				{step === "signin" && (
					<>
						<div className="w-full flex flex-col gap-1.5">
							<label htmlFor="email" className="text-sm text-muted">
								{t("auth.email")} <span className="text-accent">*</span>
							</label>
							<Field className={INPUT_CLASS} type="email" name="email" placeholder={t("auth.enter_email")} id="email" />
						</div>
						<div className="w-full flex flex-col gap-1.5">
							<label htmlFor="password" className="text-sm text-muted">
								{t("auth.password")} <span className="text-accent">*</span>
							</label>
							<Field className={INPUT_CLASS} type="password" name="password" placeholder={t("auth.enter_password")} id="password" />
						</div>
					</>
				)}
				{step === "verify" && (
					<div className="w-full flex flex-col gap-1.5">
						<label htmlFor="code" className="text-sm text-muted">
							{t("auth.enter_code")} <span className="text-accent">*</span>
						</label>
						<Field className={`${INPUT_CLASS} tracking-[0.4em] text-center`} type="text" name="code" placeholder="XXXXXX" id="code" />
					</div>
				)}
			</SmartForm>

			{step === "signin" && (
				<div className="text-center flex flex-col items-center gap-2 text-sm">
					<div className="flex items-center gap-2">
						<span className="text-muted">{t("auth.dont_have_account")}</span>
						<NextLink href="/auth/signup" className="text-accent font-medium hover:underline">
							{t("auth.signup")}
						</NextLink>
					</div>
					<NextLink href="/auth/reset" className="text-muted-2 hover:text-foreground transition-colors">
						{t("auth.forgot_password")}
					</NextLink>
				</div>
			)}
		</div>
	);
}
