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

function signin(response: any, setResponseData: any, t: any) {
	const { access, refresh, user } = response.data.data;

	// clear old values if exist
	Cookies.remove("access");
	Cookies.remove("refresh");
	Cookies.remove("user");
	Cookies.remove("sessionid");

	// set new values
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
					}, 2000);
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
		<SmartForm
			onSubmit={onSubmit}
			submitLabel={step === "signin" ? t("auth.signin") : t("auth.confirm")}
			loadingLabel={t("status.loading")}
			className="flex-1 h-full flex flex-col gap-8 items-center px-10 lg:py-10 py-20 overflow-auto w-full"
		>
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
			<NextLink href="/" className="w-full flex justify-center">
				<img src="/images/logo/base.svg" alt="Logo" className="max-w-[200px]" />
			</NextLink>
			<div className="text-center">
				<h4 className="text-xl font-bold text-neutral-700">{t("auth.title")}</h4>
				<p className="text-md text-yellow-400">{t("auth.subtitle")}</p>
			</div>

			<SocialAuthButtons />

			<div className="py-5 w-full">
				<div className="relative flex items-center justify-center border-b border-gray-500">
					<span className="absolute px-6 py-1 text-sm rounded-sm bg-gray-100 text-black">{t("auth.or")}</span>
				</div>
			</div>
			{step === "signin" && (
				<>
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
					<div className="w-full select-none">
						<label htmlFor="password" className="flex items-center gap-2 w-full">
							<span className="text-gray-700 font-light">{t("auth.password")}</span>
							<span className="text-rose-500 text-2xl">*</span>
						</label>
						<Field
							className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
							type="password"
							name="password"
							placeholder={t("auth.enter_password")}
							id="password"
						/>
					</div>
				</>
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
						placeholder="XXXXXX"
						id="code"
					/>
				</div>
			)}
			{step === "signin" && (
				<div className="text-center mt-3 pt-4 flex flex-col items-center gap-2">
					<div className="flex items-center gap-2">
						<span className="text-gray-500 font-light">{t("auth.dont_have_account")}</span>
						<NextLink href="/auth/signup" className="text-purple-500 text-sm">
							{t("auth.signup")}
						</NextLink>
					</div>
					<NextLink href="/auth/reset" className="text-purple-500 text-sm">
						{t("auth.forgot_password")}
					</NextLink>
				</div>
			)}
		</SmartForm>
	);
}
