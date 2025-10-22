"use client";

import { useTranslation } from "react-i18next";
import { FaChevronDown } from "react-icons/fa";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import Questions from "@/components/global/Questions";

export default function FAQSection() {
	const { t } = useTranslation("common");

	const questions = t("faq.questions", { returnObjects: true }) as {
		[key: string]: { q: string; a: string | string[] };
	};

	return (
		<main  className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
			<Breadcrumb />

			<div className="max-w-4xl mx-auto py-10 px-3">
				<h2 className="text-3xl font-semibold mb-8 text-center pb-10">
					{t("faq.title")}
				</h2>

				<div className="space-y-6">
					{Object.entries(questions).map(([key, { q, a }]) => (
						<div
							key={key}
							className="bg-neutral-900 rounded-lg shadow-md p-6"
						>
							<h3 className="text-lg font-medium flex items-center gap-2 mb-2">
								<FaChevronDown className="text-yellow-500" />
								{q}
							</h3>
							<div className="text-gray-300 text-sm space-y-2">
								{Array.isArray(a) ? (
									<ul className="list-disc pl-5">
										{a.map((item, i) => (
											<li key={i}>{item}</li>
										))}
									</ul>
								) : (
									<p>
										{a.includes("support@esai.kg") ? (
											<>
												Пишите на{" "}
												<a
													href="mailto:support@esai.kg"
													className="text-blue-500"
												>
													support@esai.kg
												</a>
												<br />
												Или через Telegram:{" "}
												<a
													href="https://t.me/VokaloSupportBot"
													target="_blank"
													className="text-blue-500"
												>
													@VokaloSupportBot
												</a>
											</>
										) : (
											a
										)}
									</p>
								)}
							</div>
						</div>
					))}
				</div>
			</div>

			<Questions />
		</main>
	);
}
