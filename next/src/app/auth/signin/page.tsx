"use client";

import "@/assets/style.scss";
import { useState, useEffect } from "react";
import { fetchData } from "@/tools/fetchData";
import { InputHTMLAttributes } from "react";
import { useTranslation } from "react-i18next";
import { Alert } from "@/components/UI/Alert/Alert";
import { Button } from "@/components/UI/Buttons/Buttons";
import { Field } from "@/components/UI/Inputs/Inputs";
import NextLink from "@/components/UI/NextLink/NextLink";
import formEntries from "@/tools/formEntries";
import Cookies from "js-cookie";

export default function SignIn() {
	const { t } = useTranslation("common");

	const [step, setStep] = useState<"signin" | "verify">("signin");
	const [formState, setFormState] = useState<{ email?: string }>({});

	const [withEmail, setWithEmail] = useState(true);
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
					window.location.href = "/dashboard";
				}, 2000);
			}
		}
	}, [responseData]);

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();
		const formData = formEntries(e.target as HTMLFormElement);

		if (step === "signin") {
			const email = formData.email;
			setFormState({ email });

			fetchData("users/signin/", "POST", formData)
				.then((response) => {
					if (response?.data?.status === "success") {
						setStep("verify");
						setResponseData({
							status: "info",
							title: t("status.code_sent"),
							message: t("status_extended.check_email"),
						});
					} else {
						setResponseData({
							status: "error",
							title: t("status.error"),
							message: response?.data?.message || t("status_extended.error_username_password"),
						});
					}
				})
				.catch((error) => {
					setResponseData({
						status: "error",
						title: t("status.error"),
						message: error.message || t("status_extended.error"),
					});
				});
		}

		if (step === "verify") {
			const code = formData.code;

			fetchData("users/signin/confirm/", "POST", {
				email: formState.email,
				code: code,
			}).then((response) => {
				if (response?.data?.status === "authenticated") {
					const { access, refresh, user } = response.data.data;
					Cookies.set("access", access);
					Cookies.set("refresh", refresh);
					Cookies.set("user", JSON.stringify(user));
					
					setResponseData({
						status: "success",
						title: t("status.success"),
						message: t("status_extended.success"),
					});
				} else {
					setResponseData({
						status: "error",
						title: t("status.error"),
						message: response?.data?.message || t("status_extended.invalid_code"),
					});
				}
			});
		}
	};

	return (
		<form onSubmit={handleSubmit} className="flex-1 h-full flex flex-col gap-8 items-center p-10 overflow-auto">
			<Alert
				show={showAlert}
				title={alertTitle}
				message={alertMessage}
				type={alertType}
				onClose={() => setShowAlert(false)}
				className="mb-4"
				autoClose
				autoCloseDuration={2000}
				position="top"
				closeButton
			/>

			<img src="/images/logo/base.svg" alt="" className="max-w-[200px]" />
			<div className="text-center">
				<h4 className="text-xl font-bold text-black">{t("auth.title")}</h4>
				<p className="text-md text-yellow-500">{t("auth.subtitle")}</p>
			</div>

			{step === "signin" && (
				<>
					{/* email / phone выбор */}
					<div className="w-full select-none flex flex-col">
						<label htmlFor="email" className="flex items-center gap-2 w-full">
							<span className="text-gray-700 font-light">{t("auth.email")}</span>
							<span className="text-rose-500 text-2xl">*</span>
						</label>
						<Field
							className="bg-white border border-white text-black white-field-style text-sm"
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
							className="bg-white border border-white text-black white-field-style text-sm"
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
						className="bg-white border border-white text-black white-field-style text-sm"
						type="text"
						name="code"
						placeholder="XXXXXX"
						id="code"
					/>
				</div>
			)}

			<Button
				className="w-full px-3 py-2 rounded-md"
				type="submit"
				style={{ background: "linear-gradient(45deg, #6b3bfa, #f11e76)" }}
			>
				{step === "signin" ? t("auth.signin") : t("auth.confirm")}
			</Button>

			{step === "signin" && (
				<div className="text-center mt-3 pt-4 flex flex-col items-center gap-2">
					<div className="flex items-center gap-2">
						<span className="text-yellow-500 font-light">{t("auth.dont_have_account")}</span>
						<NextLink href="/auth/signup" className="text-purple-500 text-sm">
							{t("auth.signup")}
						</NextLink>
					</div>
					<NextLink href="/auth/reset" className="text-purple-500 text-sm">
						{t("auth.forgot_password")}
					</NextLink>
				</div>
			)}
		</form>
	);
}
