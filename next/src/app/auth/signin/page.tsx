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
	// 2-шаговый email-OTP без пароля: request (ввод email) -> verify (ввод кода)
	const [step, setStep] = useState<"request" | "verify">("request");
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
		// Шаг 1 — запрос кода: POST users/signin/ { email }
		if (step === "request") {
			const email = data.email;
			setFormState({ email });
			const response = await fetchData("users/signin/", "POST", { email }).catch((error) => ({
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
				// На случай, если бэк сразу авторизует (например доверенная сессия)
				signin(response, setResponseData, t);
			} else {
				setResponseData({
					status: "error",
					title: t("status.error"),
					message: response?.data?.message || t("status_extended.error"),
				});
			}
		}
		// Шаг 2 — подтверждение кода: POST users/signin/confirm/ { email, code }
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
				<h1 className="text-2xl font-bold text-foreground">{t("auth.login", { defaultValue: "Войти" })}</h1>
			</div>

			{/* CTA клиента — заметный блок с золотым акцентом на «3 000 кредитов» */}
			<div className="rounded-2xl border border-accent/40 bg-accent/[0.07] px-5 py-4 text-center">
				<p className="text-base sm:text-lg font-semibold text-foreground leading-snug">
					{t("auth.cta_part1", { defaultValue: "Войди в 1 клик и получи" })}{" "}
					<span className="text-accent font-bold">{t("auth.cta_credits", { defaultValue: "3 000 кредитов" })}</span>.
				</p>
				<p className="text-sm text-muted mt-1">
					{t("auth.cta_part2", { defaultValue: "Без карты. Без подписок." })}
				</p>
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
				submitLabel={step === "request" ? t("auth.get_code", { defaultValue: "Получить код" }) : t("auth.login", { defaultValue: "Войти" })}
				loadingLabel={t("status.loading")}
				className="w-full flex flex-col gap-4"
			>
				{step === "request" && (
					<div className="w-full flex flex-col gap-1.5">
						<label htmlFor="email" className="text-sm text-muted">
							{t("auth.email")} <span className="text-accent">*</span>
						</label>
						<Field className={INPUT_CLASS} type="email" name="email" placeholder={t("auth.enter_email")} id="email" />
					</div>
				)}
				{step === "verify" && (
					<div className="w-full flex flex-col gap-1.5">
						<label htmlFor="code" className="text-sm text-muted">
							{t("auth.enter_code")} <span className="text-accent">*</span>
						</label>
						<p className="text-xs text-muted-2">
							{t("auth.code_sent_to", { defaultValue: "Код отправлен на email" })}
							{formState.email ? ` ${formState.email}` : ""}
						</p>
						<Field className={`${INPUT_CLASS} tracking-[0.4em] text-center`} type="text" name="code" placeholder="XXXXXX" id="code" />
					</div>
				)}
			</SmartForm>

			{/* Подпись: аккаунт создаётся автоматически при первом входе. Без ссылок на регистрацию/сброс пароля. */}
			<p className="text-center text-xs text-muted-2">
				{t("auth.auto_create_hint", { defaultValue: "Впервые? Аккаунт создастся автоматически." })}
			</p>
		</div>
	);
}
