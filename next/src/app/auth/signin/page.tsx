"use client";

import "@/assets/style.scss";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { Alert } from "@/components/ui/alert/Alert";
import { Field } from "@/components/ui/inputs/Inputs";
import NextLink from "@/components/ui/nextLink/NextLink";
import EsaiLogo from "@/components/brand/EsaiLogo";
import { fetchData } from "@/tools/fetchData";
import SmartForm from "@/components/forms/SmartForm";
import SocialAuthButtons from "@/components/auth/SocialAuthButtons";
import { useBonusSettings } from "@/hooks/useBonusSettings";
import { trackRegistration } from "@/tools/analytics";
import { deviceKeyHeader } from "@/tools/deviceKey";
import { rememberReturnPath, takeReturnPath } from "@/tools/authNext";

const INPUT_CLASS =
	"w-full rounded-xl bg-surface-2 border border-border text-foreground placeholder:text-muted-2 text-sm px-4 py-3 focus:border-accent focus:outline-none transition-colors";

function signin(response: any, setResponseData: any, t: any) {
	// Безопасный гард: не деструктурируем data вслепую — при ошибочном payload это крашит.
	const payload = response?.data?.data;
	if (!response?.ok || !payload || !payload.access || !payload.refresh) {
		setResponseData({
			status: "error",
			title: t("status.error"),
			message: t("status_extended.error"),
		});
		return;
	}
	const { access, refresh, user } = payload;

	Cookies.remove("access");
	Cookies.remove("refresh");
	Cookies.remove("user");
	Cookies.remove("sessionid");

	// Cookie-хардненинг: secure + sameSite lax (lax переживает возврат из OAuth); access короткоживущий.
	Cookies.set("access", access, { expires: 0.5, secure: true, sameSite: "lax" });
	Cookies.set("refresh", refresh, { expires: 15, secure: true, sameSite: "lax" });
	if (user !== undefined) {
		Cookies.set("user", JSON.stringify(user), { secure: true, sameSite: "lax" });
	}

	// Новый пользователь → показать приветственное окно + засчитать конверсию
	// «Регистрация» в Google Ads и цель «registration» в Яндекс.Метрике (ТОЛЬКО
	// для нового аккаунта, после подтверждения сервером — здесь уже есть JWT,
	// значит аккаунт действительно создан).
	try {
		if (payload.is_new) {
			localStorage.setItem("esai-show-welcome", "1");
			try { (window as any).gtag_report_conversion?.(); } catch {}
			// Уход отсюда происходит через 1.5 с (см. useEffect по responseData),
			// так что ждать отправки не нужно — успевает.
			trackRegistration();
		}
	} catch {}

	setResponseData({
		status: "success",
		title: t("status.success"),
		message: t("status_extended.success"),
	});
}

export default function SignIn() {
	const { t } = useTranslation("common");
	// Размер приветственного бонуса берём из админки, а не хардкодим в тексте.
	const bonus = useBonusSettings();
	// 2-шаговый email-OTP без пароля: request (ввод email) -> verify (ввод кода)
	const [step, setStep] = useState<"request" | "verify">("request");
	const [formState, setFormState] = useState<{ email?: string }>({});
	// Необязательный промокод: сохраняем в cookie esai_promo (30 дней) до отправки
	// формы — бэк активирует его при создании аккаунта. Не влияет на сам вход.
	const [promo, setPromo] = useState("");
	const [responseData, setResponseData] = useState<any>(null);
	const [showAlert, setShowAlert] = useState(false);
	const [alertTitle, setAlertTitle] = useState(t("status.success"));
	const [alertMessage, setAlertMessage] = useState("");
	const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");

	// Реф-код из ?ref → cookie esai_ref (на случай прямой ссылки /auth/signin?ref=).
	// Основной путь ставит cookie на /auth/signup, но дублируем для надёжности.
	useEffect(() => {
		try {
			const params = new URLSearchParams(window.location.search);
			const ref = params.get("ref");
			if (ref) Cookies.set("esai_ref", ref, { expires: 30, sameSite: "lax" });
			// Куда вернуть после входа. Запоминаем сразу: кнопки Google и
			// Telegram уводят со страницы, и параметр из адреса до колбэка не доедет.
			const next = params.get("next");
			if (next) rememberReturnPath(next);
			// Промокод: из ?promo или ранее сохранённой cookie → префилл поля.
			const promoParam = params.get("promo");
			const saved = Cookies.get("esai_promo");
			const initial = (promoParam || saved || "").trim();
			if (initial) {
				setPromo(initial);
				Cookies.set("esai_promo", initial, { expires: 30, sameSite: "lax" });
			}
		} catch {}
	}, []);

	// Пишем промокод в cookie на каждый ввод, чтобы он точно ушёл на бэк при
	// регистрации (в т.ч. через соц-вход, который уходит с текущего origin).
	const onPromoChange = (value: string) => {
		setPromo(value);
		try {
			const v = value.trim();
			if (v) Cookies.set("esai_promo", v, { expires: 30, sameSite: "lax" });
			else Cookies.remove("esai_promo");
		} catch {}
	};

	useEffect(() => {
		if (responseData) {
			setShowAlert(true);
			setAlertTitle(responseData.title || t("status.success"));
			setAlertMessage(responseData.message || t("status_extended.success"));
			setAlertType(responseData.status || "warning");
			if (responseData.status === "success") {
				setTimeout(() => {
					// Раньше здесь всегда был чат — и гость, пришедший из студии
					// или тарифов «с возвратом», терял то, ради чего входил.
					window.location.href = takeReturnPath(
						"/dashboard/text-chat",
						new URLSearchParams(window.location.search).get("next"),
					);
				}, 1500);
			}
		}
	}, [responseData, t]);

	const onSubmit = async (data: any) => {
		// Шаг 1 — запрос кода: POST users/signin/ { email }
		if (step === "request") {
			const email = data.email;
			setFormState({ email });
			// X-Device-Key — постоянный UUID устройства. Нужен для блокировок:
			// по нему видно, что «новый» пользователь заходит с устройства, где
			// уже заводили аккаунт.
			const response = await fetchData("users/signin/", "POST", { email }, false, deviceKeyHeader()).catch((error) => ({
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
			const response = await fetchData(
				"users/signin/confirm/",
				"POST",
				{ email: formState.email, code: data.code },
				false,
				deviceKeyHeader(),
			).catch((error) => ({ data: { status: "error", message: error.message } }));
			if (response?.data?.status === "authenticated") {
				signin(response, setResponseData, t);
			} else {
				// 429 — замок от перебора (подождать / завтра): «код неверен» тут неправда,
				// и верный код человек вводил бы снова и снова. Причину сервер пишет в error.
				const locked = "status" in response && response.status === 429 ? response.data?.error : "";
				setResponseData({
					status: "error",
					title: t("status.error"),
					message: response?.data?.message || locked || t("status_extended.invalid_code"),
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
				<EsaiLogo className="h-8 w-auto" />
			</NextLink>

			<div className="text-center space-y-1">
				<h1 className="text-2xl font-bold text-foreground">{t("auth.login", { defaultValue: "Войти" })}</h1>
			</div>

			{/* CTA клиента — заметный блок с золотым акцентом на «3 000 кредитов» */}
			<div className="rounded-2xl border border-accent/40 bg-accent/[0.07] px-5 py-4 text-center">
				{/* Про бонус за регистрацию больше не обещаем: клиент его убрал,
				    кредиты теперь начисляются каждый день. Числа в тексте нет
				    намеренно — размер меняется в админке. */}
				<p className="text-base sm:text-lg font-semibold text-foreground leading-snug">
					{t("auth.cta_part1", {
						defaultValue: "🎁 Войдите в 1 клик и получайте бесплатные кредиты каждый день.",
					})}
				</p>
				<p className="text-sm text-muted mt-1">
					{t("auth.cta_part2", { defaultValue: "Без карты. Без подписки." })}
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
					<>
						<div className="w-full flex flex-col gap-1.5">
							<label htmlFor="email" className="text-sm text-muted">
								{t("auth.email")} <span className="text-accent">*</span>
							</label>
							<Field className={INPUT_CLASS} type="email" name="email" placeholder={t("auth.enter_email")} id="email" />
						</div>
						{/* Необязательный промокод. Значение хранится вне SmartForm (в cookie),
						    поэтому name не задаём — чтобы не попасть в payload входа. */}
						<div className="w-full flex flex-col gap-1.5">
							<label htmlFor="promo" className="text-sm text-muted">
								{t("auth.promo_label", { defaultValue: "Промокод (необязательно)" })}
							</label>
							<input
								id="promo"
								type="text"
								className={`${INPUT_CLASS} uppercase`}
								value={promo}
								onChange={(e) => onPromoChange(e.target.value)}
								placeholder={t("auth.promo_ph", { defaultValue: "Введите промокод" })}
								autoComplete="off"
							/>
						</div>
					</>
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
