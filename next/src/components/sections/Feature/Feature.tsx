'use client';

import "./Feature.scss";
import FeatureTabs from "./FeatureTabs";
import { TextTag } from "@/components/ui/text/Text";
import { useTranslation } from "react-i18next";

export default function SectionFeature() {

	const { t } = useTranslation('home');
	const title = t("hero.title");
	const subtitle = t("hero.subtitle");

	return (
		<section className="px-30 py-30 antialiased text-center flex flex-col gap-7 items-center relative overflow-hidden section-divider">
			<div className="absolute top-0 flex justify-center h-full w-full -z-5">
				<img
					src="/images/decorations/feature-shape-left.webp"
					alt=""
					className="absolute top-0 left-0 opacity-70"
				/>
				<img src="/images/decorations/feature-top.webp" alt="" className="absolute -z-30 top-0 opacity-70" />
				<img src="/images/decorations/feature-shape-right.webp" alt="" className="absolute top-0 right-0" />

				<img
					src="/images/decorations/feature-2-shape-3.webp"
					alt=""
					className="absolute -z-30 bottom-0 left-0 opacity-70"
				/>
				<img src="/images/decorations/feature-2-shape-4.webp" alt="" className="absolute bottom-0 right-0" />
			</div>

			<div className="flex flex-col gap-10 items-center">

				<TextTag text={`${subtitle}`}/>
				<h4 className="text-5xl">{`${title}`}</h4>
			</div>

			<FeatureTabs />
		</section>
	);
}
