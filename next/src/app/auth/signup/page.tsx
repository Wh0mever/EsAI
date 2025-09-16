"use client";

import "@/assets/style.scss";
import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert } from "@/components/ui/alert/Alert";
import { Field } from "@/components/ui/inputs/Inputs";
import NextLink from "@/components/ui/nextLink/NextLink";
import { fetchData } from "@/tools/fetchData";
import SmartForm from "@/components/forms/SmartForm";

type ApiOk = { status: "success"; title?: string; message?: string };
type ApiErr = { status: "error"; title?: string; message?: string; errors?: Record<string, string[] | string> };
type ApiPayload = ApiOk | ApiErr | any;

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
			const msg =
				responseData.message || formatErrors((responseData as ApiErr).errors) || t("status_extended.error");

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
		<SmartForm
			onSubmit={onSubmit}
			submitLabel={t("auth.signup")}
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
				autoClose={autoClose}
				autoCloseDuration={2000}
				closeButton
			/>

			<NextLink href="/" className="w-full flex justify-center">
				<img src="/images/logo/base.svg" alt="Logo" className="max-w-[200px]" />
			</NextLink>

			<div className="flex flex-col gap-2 items-center">
				<h4 className="text-xl font-bold text-neutral-700 text-center">{t("auth.title")}</h4>
				<p className="text-md text-yellow-400">{t("auth.subtitle")}</p>
			</div>

			<a
				href="http://127.0.0.1/accounts/google/login/?process=login"
				className="flex gap-3 items-center justify-center bg-white text-black py-2 px-6 w-full rounded-md font-light text-sm"
			>
				<img src="/images/icons/google-icon.svg" alt="Google" />
				<span>{t("auth.google")}</span>
			</a>

			<div className="py-5 w-full">
				<div className="relative flex items-center justify-center border-b border-gray-500">
					<span className="absolute px-6 py-1 text-sm rounded-sm bg-gray-100 text-black">{t("auth.or")}</span>
				</div>
			</div>

			<div className="w-full flex flex-col gap-4">
				<div className="w-full select-none flex flex-col">
					<label htmlFor="name" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.fullname")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="text"
						name="name"
						placeholder={t("auth.enter_fullname")}
						id="name"
					/>
				</div>

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

				<div className="w-full select-none flex flex-col">
					<label htmlFor="tel" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.tel")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="tel"
						name="tel"
						placeholder="+xxxxxxxxxxxxx"
						id="tel"
					/>
				</div>

				<div className="w-full select-none flex flex-col">
					<label htmlFor="referral_uid" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.referral_code")}</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="text"
						name="referral_uid"
						placeholder={t("auth.enter_referral_code")}
						id="referral_uid"
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

				<div className="w-full select-none">
					<label htmlFor="password_repeat" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.confirm_password")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm px-3 py-2"
						type="password"
						name="password_repeat"
						placeholder={t("auth.confirm_password")}
						id="password_repeat"
					/>
				</div>
			</div>

			<div className="text-center mt-3 pt-4 mb-0 flex flex-col items-center gap-2">
				<div className="flex items-center gap-2">
					<span className="text-gray-500 font-light">{t("auth.have_account")}</span>
					<NextLink href="/auth/signin" className="text-purple-500 text-sm">
						{t("auth.signin")}
					</NextLink>
				</div>
			</div>
		</SmartForm>
	);
}
