'use client';
import ReviewCarousel from "@/components/sections/Feedback/FeedBackCarousel";
import { t } from "i18next";
import { useTranslation } from "react-i18next";

export default function FeedBack() {

	const { t } = useTranslation('home');

	return (
		<section className="px-30 pt-20 lg:pt-80 flex flex-col items-center gap-5 relative">
			<div className="">
				<h2 className="text-3xl text-center">{t('feedback.title')}</h2>
			</div>
			<img src="/images/decorations/testimonial-4-shape-dots.webp" alt="" className="absolute -z-10 -top-20" />
			<img
				src="/images/decorations/testimonial-4-shape-circle.webp"
				alt=""
				className="absolute -z-10 transform top-50"
			/>

			<div className="w-full py-10 flex flex-col">
				<ReviewCarousel startDirection="left" speed={1} />
				<ReviewCarousel startDirection="right" speed={0.5} />
			</div>
		</section>
	);
}
