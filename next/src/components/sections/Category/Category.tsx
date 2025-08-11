"use client";

import React, { useState, useEffect } from "react";
import { BsStars } from "react-icons/bs";
import { Button } from "@/components/ui/buttons/Buttons";
import { CiHeart } from "react-icons/ci";
import { TextTag } from "@/components/ui/text/Text";
import { useTranslation } from "react-i18next";

type Card = {
	title: string;
	description: string;
};

type Data = {
	[category: string]: Card[];
};

const data: Data = {
	"Social Media": [
		{ title: "Twitter Post", description: "" },
		{ title: "Discount Promotion", description: "" },
		{ title: "Social Media Bio", description: "" },
		{ title: "Facebook Ads", description: "" },
		{ title: "Instagram Captions", description: "" },
	],
	"Blog Contents": [
		{ title: "Blog Post", description: "" },
		{ title: "Blog Post Ideas", description: "" },
	],
	"Email Templates": [{ title: "Email Newsletter", description: "" }],
	Videos: [
		{ title: "YouTube Video Script", description: "" },
		{ title: "Video Title", description: "" },
		{ title: "Video Description", description: "" },
	],
};

export default function Category() {
	const { t } = useTranslation('home');
	const categories = t('aiTemplates.categories', { returnObjects: true }) as string[];
	const allCards = Object.values(data).flat();
	const [selectedCategory, setSelectedCategory] = useState(categories[0]);
	const visibleCards = selectedCategory === categories[0] ? allCards : data[selectedCategory] || [];

	return (
		<section className="px-30 py-20 section-divider flex flex-col gap-5">
			<img src="/images/decorations/ai-tools-shape-left.webp" alt="" className="absolute left-0 top-0 -z-10" />
			<div className="mt-2 flex flex-col items-center justify-center gap-5 text-center">
				<TextTag text={t('aiTemplates.subtitle')} />
				<h2 className="text-4xl font-semibold">{t('aiTemplates.title')}</h2>
			</div>

			<div className="flex flex-wrap justify-center gap-2 py-5 w-full lg:w-7/12 mx-auto">
				{categories.map((category) => (
					<Button
						key={category}
						className={`px-4 py-1.5 rounded-xl text-sm font-medium transition-colors ${
							selectedCategory === category
								? "bg-indigo-600/50 text-white"
								: "bg-neutral-800/25 text-gray-300 hover:bg-neutral-700"
						}`}
						onClick={() => setSelectedCategory(category)}
					>
						{category}
					</Button>
				))}
			</div>

			<div className="grid grid-cols-1 sm:grid-cols-1 md:grid-cols-2 gap-5">
				{visibleCards.map((card, index) => (
					<div
						key={index}
						className={`flex flex-col gap-3 p-10 card-hover-colored bg-gray-800/5 border border-gray-700 rounded-xl hover:shadow-lg hover:bg-gray-800/10 hover:border-gray-600 colored-center`}
						style={{ animation: "showCard 0.5s ease-in-out forwards" }}
					>
						<img
							src="/images/decorations/ai-template-card-bg.webp"
							alt=""
							className="absolute h-full w-full left-0 top-0 -z-10"
						/>

						<i className="text-3xl p-5 flex rounded-full w-fit h-fit bg-indigo-800/25 text-white">
							<BsStars />
						</i>
						<div>
							<h3 className="text-white font-semibold text-lg">{card.title}</h3>
							{card.description && <p className="text-gray-400 text-sm mt-1">{card.description}</p>}
						</div>
						<div className="text-gray-500 flex items-center justify-between mt-3">
							<p className="text-sm ">0 generated</p>
							<Button className="text-2xl cursor-pointer flex items-center justify-center p-2 rounded-full hover:text-indigo-600 hover:bg-white/75 transition-colors">
								<CiHeart className="inline-block mr-1" />
							</Button>
						</div>
					</div>
				))}
			</div>
		</section>
	);
}
