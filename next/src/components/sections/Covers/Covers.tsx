"use client";

import FeatureCard from "../Feature/FeatureCard";
import AIGalleryStrips from "./Tape";
import { TextTag } from "@/components/ui/text/Text";
import { useTranslation } from "react-i18next";
import "./Covers.scss";

export default function Covers() {
	const { t } = useTranslation("home");

	return (
		<section className="px-10 py-20 lg:px-30 lg:py-30 section-divider flex flex-col gap-5 bg-black/50">
			<div className="absolute w-full h-full top-0 left-0">
				<img
					src="/images/decorations/ai-image-shape-top.webp"
					alt=""
					className="absolute top-0 left-1/2 transform -translate-x-1/2"
				/>
				<img src="/images/decorations/ai-image-shape-right.webp" alt="" className="absolute right-0 top-0" />
				<img src="/images/decorations/ai-image-shape-left.webp" alt="" className="absolute left-0 top-0" />
			</div>

			<div className="z-10 w-full flex flex-col gap-10">
				<div className="mt-2 flex flex-col items-center justify-center gap-5 text-center">
					<TextTag text={t("covers.subtitle")} />
					<h2 className="text-4xl font-semibold">{t("covers.title")}</h2>
				</div>

				<div className="w-full flex flex-wrap">
					<div className="w-full lg:w-3/12 p-4">
						<FeatureCard
							title={t("covers.cards.0.title")}
							image="/images/feature/5.webp"
							description={t("covers.cards.0.description")}
						/>
					</div>
					<div className="lg:w-6/12 p-4 w-12/12">
						<FeatureCard
							title={t("covers.cards.1.title")}
							image="/images/feature/6.webp"
							description={t("covers.cards.1.description")}
						/>
					</div>
					<div className="w-full lg:w-3/12 p-4">
						<FeatureCard
							title={t("covers.cards.2.title")}
							image="/images/feature/7.webp"
							description={t("covers.cards.2.description")}
						/>
					</div>
				</div>

				<div className="gallery-vignette px-5 py-20 rounded-lg">
					<AIGalleryStrips />
				</div>
			</div>
		</section>
	);
}
