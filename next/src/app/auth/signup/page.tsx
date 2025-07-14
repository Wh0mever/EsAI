"use client";

import "@/assets/style.scss";
import { useState, useEffect } from "react";
import { Button } from "@/components/UI/Buttons/Buttons";
import { Field } from "@/components/UI/Inputs/Inputs";
import { fetchData } from "@/tools/fetchData";
import formEntries from "@/tools/formEntries";
import NextLink from "@/components/UI/NextLink/NextLink";
import { Alert } from "@/components/UI/Alert/Alert";
import { useTranslation } from "react-i18next";


function SignUpRequest(e: any) {
	e.preventDefault();
	console.log("SignUpRequest function called");
}

export default function SignUp() {
	const { t } = useTranslation("common");

	const [responseData, setResponseData] = useState<any>(null);
	const [showAlert, setShowAlert] = useState(false);
	const [alertTitle, setAlertTitle] = useState("Успешно");
	const [alertMessage, setAlertMessage] = useState("");
	const [alertType, setAlertType] = useState<"success" | "error" | "info" | "warning">("info");

	useEffect(() => {
		if (responseData) {
			setShowAlert(true);
			setAlertTitle(responseData.title || t("status."));
			setAlertMessage(responseData.message || t("status_extended.success"));
			setAlertType(responseData.status || "warning");
			if (responseData.status === "success") {
				setTimeout(() => {
					window.location.href = "/auth/signin";
				}, 2000);
			}
		}
	}, [responseData]);



	return (
		<form
			className="flex-1 overflow-auto h-full flex flex-col gap-8 items-center p-10"
			method="POST"
			onSubmit={(e) => {
				e.preventDefault();
				const fromData = formEntries(e.target as HTMLFormElement);
				fetchData("users/signup/", "POST", fromData)
					.then((response) => {
						if (response) {
							setResponseData(response.data);
						}
					})
					.catch((error) => {
						setResponseData({
							status: "error",
							title: t("status.error"),
							message: error.message || t("status_extended.error"),
						});
					});
			}}
		>
			<Alert
				show={showAlert}
				title={alertTitle}
				message={alertMessage}
				type={alertType}
				onClose={() => setShowAlert(false)}
				className="mb-4"
				autoClose={true}
				autoCloseDuration={2000}
				position="top"
				closeButton={true}
			/>

			<img src="/images/logo/base.svg" alt="" className="max-w-[200px]" />
			<div className="flex flex-col gap-2 items-center">
				<h4 className="text-xl font-bold text-black text-center">{t("auth.title")}</h4>
				<p className="text-md text-yellow-500">{t("auth.subtitle")}</p>
			</div>

			<Button
				onClick={() => {}}
				className="flex gap-3 items-center justify-center bg-white text-black py-2 px-6 w-full rounded-md font-light text-sm"
			>
				<img src="/images/icons/google-icon.svg" alt="Google" />
				<span>{t("auth.google")}</span>
			</Button>

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
						className="bg-white border border-white text-black white-field-style text-sm"
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
						className="bg-white border border-white text-black white-field-style text-sm"
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
						className="bg-white border border-white text-black white-field-style text-sm"
						type="tel"
						name="tel"
						placeholder="+xxxxxxxxxxxxx"
						id="tel"
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
				<div className="w-full select-none">
					<label htmlFor="password_repeat" className="flex items-center gap-2 w-full">
						<span className="text-gray-700 font-light">{t("auth.confirm_password")}</span>
						<span className="text-rose-500 text-2xl">*</span>
					</label>
					<Field
						className="bg-white border border-white text-black white-field-style text-sm"
						type="password"
						name="password_repeat"
						placeholder={t("auth.confirm_password")}
						id="password_repeat"
					/>
				</div>
			</div>

			<Button
				className="w-full px-3 py-2 rounded-md"
				type="submit"
				style={{
					background: "linear-gradient(45deg, #6b3bfa, #f11e76)",
				}}
			>
				{t("auth.signup")}
			</Button>

			<div className="font-monospace fw-medium text-center text-muted mt-3 pt-4 mb-0 flex flex-col items-center gap-2">
				<div className="flex items-center gap-2">
					<span className="text-yellow-500 font-light">{t("auth.have_account")}</span>
					<NextLink href="/auth/signin" className="text-purple-500 text-sm">
						{t("auth.signin")}
					</NextLink>
				</div>
			</div>
		</form>
	);
}
