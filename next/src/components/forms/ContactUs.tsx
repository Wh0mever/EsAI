"use client";

import { Field, TextArea } from "@/components/ui/inputs/Inputs";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoIosArrowRoundForward } from "react-icons/io";
import { useTranslation } from "react-i18next";
import SmartForm from "@/components/forms/SmartForm";
import { fetchData } from "@/tools/fetchData";
import { useState } from "react";
import { Alert } from "@/components/ui/alert/Alert";

export default function ContactUsForm() {
	const { t } = useTranslation("common");
	const [ok, setOk] = useState(false);
	const [failed, setFailed] = useState(false);

	return (
		<>
			<SmartForm
				className="flex flex-col gap-5 w-full"
				onSubmit={async (data: any, form) => {
					// map frontend->backend fields
					const payload = {
						name: data.name || "",
						email: data.email,
						tel: data.phone || "",
						question: data.message || "",
					};
					setOk(false);
					setFailed(false);
					// fetchData не бросает исключений на 4xx/5xx — раньше «Сообщение
					// отправлено» показывалось и тогда, когда вопрос не дошёл.
					const res = await fetchData("users/question/", "POST", payload, false);
					if (res.ok) {
						setOk(true);
						form.reset();
					} else {
						setFailed(true);
					}
				}}
				submitLabel={t("contact_us.submit_button")}
			>
				<h2 className="text-2xl">{t("contact_us.form_title")}</h2>
				<p className="text-muted">{t("contact_us.form_subtitle")}</p>

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
					/>
				</div>

				<TextArea
					name="message"
					label={t("contact_us.message_label")}
					className="w-full dark-field min-h-[100px]"
					required
				/>
			</SmartForm>

			<Alert
				show={ok}
				onClose={() => setOk(false)}
				type="success"
				title={t("common.success")}
				message={t("faq.message_sended")}
				position="bottom"
				offset={20}
				autoClose
				autoCloseDuration={3000}
				closeButton
			/>

			<Alert
				show={failed}
				onClose={() => setFailed(false)}
				type="error"
				title={t("contact_us.error_title", { defaultValue: "Не удалось отправить" })}
				message={t("contact_us.error_text", {
					defaultValue: "Сообщение не отправлено. Проверьте интернет и попробуйте ещё раз или напишите нам на support@esai.kg.",
				})}
				position="bottom"
				offset={20}
				autoCloseDuration={6000}
				closeButton
			/>
		</>
	);
}
