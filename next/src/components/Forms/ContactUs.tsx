"use client";

import { Field, TextArea } from "@/components/UI/Inputs/Inputs";
import { Button } from "@/components/UI/Buttons/Buttons";
import { IoIosArrowRoundForward } from "react-icons/io";
import { useTranslation } from "react-i18next";

export default function ContactUsForm() {
	const { t } = useTranslation("common");

	return (
		<form className="flex flex-col gap-5 w-full">
			<h2 className="text-2xl">{t("contact_us.form_title")}</h2>
			<p className="text-gray-400">{t("contact_us.form_subtitle")}</p>

			<Field
				name="name"
				label={t("contact_us.name_label")}
				placeholder={t("contact_us.name_placeholder")}
				className="w-full dark-field"
				required
			/>

			<div className="flex gap-4 w-full">
				<Field
					name="email"
					type="email"
					label={t("contact_us.email_label")}
					placeholder={t("contact_us.email_placeholder")}
					className="flex-auto dark-field"
					required
				/>
				<Field
					name="phone"
					type="tel"
					label={t("contact_us.phone_label")}
					placeholder={t("contact_us.phone_placeholder")}
					className="flex-auto dark-field"
					required
				/>
			</div>

			<TextArea
				name="message"
				label={t("contact_us.message_label")}
				className="w-full dark-field min-h-[100px]"
			/>

			<Button
				onClick={() => {}}
				className="w-fit px-5 py-3 mt-2 bg-indigo-500 flex gap-1 items-center rounded hover:bg-indigo-600 duration-300"
			>
				<span>{t("contact_us.submit_button")}</span>
				<i className="text-2xl">
					<IoIosArrowRoundForward />
				</i>
			</Button>
		</form>
	);
}
