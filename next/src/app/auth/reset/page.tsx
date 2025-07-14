"use client";

import "@/assets/style.scss";
import { useState } from "react";
import { Button } from "@/components/UI/Buttons/Buttons";
import { Field } from "@/components/UI/Inputs/Inputs";
import { useTranslation } from "react-i18next";

export default function Auth() {

	const { t } = useTranslation("common");

	const [isSignIn, setIsSignIn] = useState(true);
	const [withEmail, setWithEmail] = useState(true);

	return (
		<form className="flex-1  overflow-auto h-full flex flex-col gap-8 items-center p-10">
			<img src="/images/logo/base.svg" alt="" className="max-w-[200px]" />

			<div className="w-full">
				{withEmail ? (
					<div className="w-full select-none flex flex-col">
						<label htmlFor="email" className="flex items-center gap-2 w-full">
							<span className="text-gray-700 font-light">{t('auth.email')}</span>
							<span className="text-rose-500 text-2xl">*</span>
						</label>
						<Field
							className="bg-white border border-white text-black white-field-style text-sm"
							type="email"
							name="email"
							placeholder={t('auth.enter_email')}
							id="email"
						/>
						<Button
							className="text-purple-500 text-sm mt-2 self-end"
							onClick={() => {
								setWithEmail(!withEmail);
							}}
						>
							{t('auth.reset_with_phone')}
						</Button>
					</div>
				) : (
					<div className="w-full select-none flex flex-col">
						<label htmlFor="tel" className="flex items-center gap-2 w-full">
							<span className="text-gray-700 font-light">{t('auth.tel')}</span>
							<span className="text-rose-500 text-2xl">*</span>
						</label>
						<Field
							className="bg-white border border-white text-black white-field-style text-sm"
							type="tel"
							name="tel"
							placeholder="+xxxxxxxxxxxxx"
							id="tel"
						/>
						<Button
							className="text-purple-500 text-sm mt-2 self-end"
							onClick={() => {
								setWithEmail(!withEmail);
							}}
						>
							{t('auth.reset_with_email')}
						</Button>
					</div>
				)}

			</div>

			<Button
				className="w-full px-3 py-2 rounded-md"
				onClick={() => {}}
				style={{
					background: "linear-gradient(45deg, #6b3bfa, #f11e76)",
				}}
			>
				{t('auth.resetPassword')}
			</Button>
		</form>
	);
}
