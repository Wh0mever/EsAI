"use client";

import "@/assets/style.scss";
import { IoIosArrowRoundForward } from "react-icons/io";
import ContactUsForm from "@/components/Forms/ContactUs";
import { useTranslation } from "react-i18next";

export default function ContactUs() {
	const { t } = useTranslation("common");

	return (
		<main className="pt-50 px-30">
			<div className="flex gap-5">
				<div className="flex-auto p-10 border border-gray-700 flex flex-col gap-5 rounded-lg relative overflow-hidden card-hover-colored">
					<img src="/images/logo/head.svg" alt="" className="max-w-[50px]" />
					<img src="/images/decorations/ai-template-card-bg.webp" alt="" className="absolute top-0" />
					<h5 className="text-xl font-bold">{t("contact_us.write_title")}</h5>

					<p className="text-gray-300">{t("contact_us.write_description")}</p>

					<a
						href={`mailto:${t("contact_us.write_email")}`}
						className="flex items-center gap-1 border-gray-700 border py-3 px-5 w-fit rounded-lg bg-neutral-900 hover:bg-indigo-600 transition-all duration-300"
					>
						<span>{t("contact_us.write_button")}</span>
						<i>
							<IoIosArrowRoundForward />
						</i>
						<span>{t("contact_us.write_email")}</span>
					</a>
				</div>

				<div className="flex-auto p-10 border border-gray-700 flex flex-col gap-5 rounded-lg relative overflow-hidden card-hover-colored">
					<img src="/images/logo/head.svg" alt="" className="max-w-[50px]" />
					<img src="/images/decorations/ai-template-card-bg.webp" alt="" className="absolute top-0" />

					<h5 className="text-xl font-bold">{t("contact_us.call_title")}</h5>

					<p className="text-gray-300">{t("contact_us.call_description")}</p>

					<a
						href={`tel:${t("contact_us.call_phone").replace(/[^+\d]/g, "")}`}
						className="flex items-center gap-1 border-gray-700 border py-3 px-5 w-fit rounded-lg bg-neutral-900 hover:bg-indigo-600 transition-all duration-300"
					>
						<span>{t("contact_us.call_button")}</span>
						<i>
							<IoIosArrowRoundForward />
						</i>
						<span>{t("contact_us.call_phone")}</span>
					</a>
				</div>
			</div>

			<div className="flex gap-10 w-full justify-between py-20">
				<div className="w-6/12">
					<ContactUsForm />
				</div>
				<div className="w-6/12">
					<img src="/images/decorations/contact-us.svg" className="w-full" alt="" />
				</div>
			</div>
		</main>
	);
}
