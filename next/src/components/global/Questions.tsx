"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/buttons/Buttons";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import SmartForm from "@/components/forms/SmartForm";
import { Field, TextArea } from "../ui/inputs/Inputs";
import { fetchData } from "@/tools/fetchData";
import { Alert } from "@/components/ui/alert/Alert";

export default function Questions() {
	const [open, setOpen] = useState(false);
	const [showAlert, setShowAlert] = useState(false);
	// Итог отправки: раньше «отправлено» показывалось всегда — fetchData не
	// бросает исключений, и вопрос, не дошедший до сервера, молча терялся.
	const [sendFailed, setSendFailed] = useState(false);
	const { t } = useTranslation("common");

	return (
		<div className="flex flex-col gap-5 lg:px-40 px-5 py-10 relative w-full h-fit">
			<img src="/images/decorations/pricing-faq-bottom-right.webp" className="absolute right-0 bottom-0" alt="" />

			<div className="flex flex-col gap-5 max-w-[500px]">
				<h3 className="text-3xl font-bold lg:text-center text-start">{t("faq.title")} 👍</h3>
				<p className="text-muted">
					{t("faq.text")}{" "}
					<a
						href={`mailto:${t("contact_us.write_email")}`}
						className="text-accent hover:text-accent-strong duration-300"
					>
						{t("contact_us.write_email")}
					</a>
				</p>

				<Button
					onClick={() => setOpen(true)}
					className="rounded-3xl w-fit mt-5 bg-surface-2 hover:bg-accent hover:text-on-accent duration-300 px-4 py-3"
				>
					{t("faq.button")}
				</Button>
			</div>

			<Alert
				show={showAlert}
				onClose={() => setShowAlert(false)}
				type={sendFailed ? "error" : "success"}
				title={sendFailed ? t("status.error") : t("common.success")}
				message={
					sendFailed
						? t("faq.send_error", { defaultValue: "Не удалось отправить сообщение. Проверьте интернет и попробуйте ещё раз." })
						: t("faq.message_sended")
				}
				position="bottom"
				offset={20}
				autoClose
				autoCloseDuration={3000}
				closeButton
			/>
			<Modal title={t("faq.modalTitle")} open={open} onClose={() => setOpen(false)} size="lg">
				<SmartForm
					onSubmit={async (data) => {
						const res = await fetchData("users/question/", "POST", data, false);
						if (res.ok) {
							// Форма живёт внутри модалки: закрытие размонтирует её,
							// и следующий вопрос начинается с пустых полей.
							setSendFailed(false);
							setOpen(false);
							setShowAlert(true);
						} else {
							// Модалку НЕ закрываем — введённый текст остаётся, можно
							// просто нажать «Отправить» ещё раз.
							setSendFailed(true);
							setShowAlert(true);
						}
					}}
					submitLabel={t("common.submit")}
					loadingLabel={t("common.loading")}
					className="w-full"
				>
					{/* name (optional by model) */}
					<Field
						type="text"
						name="name"
						className="px-3 py-2 border w-full border-border-strong rounded-md"
						placeholder={t("contact_us.name_placeholder") || "Name"}
						label={t("contact_us.name_label") || "Name"}
					/>

					{/* tel (optional by model) */}
					<Field
						type="tel"
						name="tel"
						className="px-3 py-2 border w-full border-border-strong rounded-md"
						placeholder={t("contact_us.phone_placeholder") || "+996..."}
						label={t("contact_us.phone_label") || "Phone"}
					/>

					<Field
						type="email"
						name="email"
						className="px-3 py-2 border w-full border-border-strong rounded-md"
						placeholder="Email"
						label="Email"
						required
					/>

					<TextArea
						name="question"
						label={t("faq.questionDescription")}
						placeholder={t("faq.questionDescriptionPlaceholder")}
						required
						className="px-3 py-2 border w-full border-border-strong rounded-md"
					/>
				</SmartForm>
			</Modal>
		</div>
	);
}
