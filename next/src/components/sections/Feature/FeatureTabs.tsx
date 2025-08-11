"use client";

import React, { useState, useEffect } from "react";
import { TbTextResize } from "react-icons/tb";
import { IoImagesOutline, IoVolumeMediumOutline } from "react-icons/io5";
import { BsChatSquareText } from "react-icons/bs";
import { SiApplemusic } from "react-icons/si";
import FeatureCard from "@/components/sections/Feature/FeatureCard";
import { Button } from "@/components/ui/buttons/Buttons";
import { TextTag } from "@/components/ui/text/Text";
import { useTranslation } from "react-i18next";




const tabCards: any = {
	songs: [
		"/images/feature/1.webp",
		"/images/feature/2.webp",
		"/images/feature/3.webp",
		"/images/feature/4.webp"
	],
	covers: [
		"/images/feature/5.webp",
		"/images/feature/6.webp",
		"/images/feature/7.webp"
	],
	voices: [
		"/images/feature/8.webp",
		"/images/feature/9.webp",
		"/images/feature/10.webp",
		"/images/feature/11.webp"
	],
	text: [
		"/images/feature/12.webp",
		"/images/feature/13.webp",
		"/images/feature/14.webp",
		"/images/feature/15.webp"
	],
	music: [
		"/images/feature/16.webp",
		"/images/feature/17.webp",
		"/images/feature/18.webp",
		"/images/feature/19.webp"
	]
};


function FeatureTab({ activeTab }: { activeTab: number }) {
	const [mounted, setMounted] = useState(false);
	const order = ["songs", "covers", "voices", "text", "music"];
	const tabKey = order[activeTab - 1];
	const cards = tabCards[order[activeTab - 1]] || [];
	const { t } = useTranslation('home');
	
	
	useEffect(() => {
		setMounted(true);
	}, []);

	return (
		<div className="py-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
			{cards.map((card: string, index: number) => (
				<div
					key={index}
					style={{ transitionDelay: `${index * 100}ms` }}
					className={`transition-all duration-700 ease-out transform
						${mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-5"}`}
				>
					<FeatureCard
						title={t(`feature.${tabKey}.${index}.description`)}
						image={card}
						description={t(`feature.${tabKey}.${index}.description`)}
					/>
				</div>
			))}
		</div>
	);
}

export default function FeatureTabs() {
	const [activeTab, setActiveTab] = useState(1);
	const { t } = useTranslation('home');

	console.log();
	return (
		<div className="feature-tabs text-white rounded-lg flex flex-col gap-10 items-center">
			<div className="tabs flex gap-10 justify-center align-center">
				<Button
					onClick={() => setActiveTab(1)}
					className={`tab text-3xl p-5  rounded-full border ${
						activeTab === 1
							? "active bg-indigo-500/25 border-indigo-500"
							: "bg-neutral-800/25 border-neutral-800"
					}`}
				>
					<TbTextResize />
				</Button>
				<Button
					onClick={() => setActiveTab(2)}
					className={`tab text-3xl p-5 duration-300 rounded-full border ${
						activeTab === 2
							? "active bg-indigo-500/25 border-indigo-500"
							: "bg-neutral-800/25 border-neutral-800"
					}`}
				>
					<IoImagesOutline />
				</Button>
				<Button
					onClick={() => setActiveTab(3)}
					className={`tab text-3xl p-5 duration-300 rounded-full border ${
						activeTab === 3
							? "active bg-indigo-500/25 border-indigo-500"
							: "bg-neutral-800/25 border-neutral-800"
					}`}
				>
					<IoVolumeMediumOutline />
				</Button>
				<Button
					onClick={() => setActiveTab(4)}
					className={`tab text-3xl p-5 duration-300 rounded-full border ${
						activeTab === 4
							? "active bg-indigo-500/25 border-indigo-500"
							: "bg-neutral-800/25 border-neutral-800"
					}`}
				>
					<BsChatSquareText />
				</Button>
				<Button
					onClick={() => setActiveTab(5)}
					className={`tab text-3xl p-5 duration-300 rounded-full border ${
						activeTab === 5
							? "active bg-indigo-500/25 border-indigo-500"
							: "bg-neutral-800/25 border-neutral-800"
					}`}
				>
					<SiApplemusic />
				</Button>
			</div>

			<TextTag text={t(`feature.tabTitles.${activeTab}`)} className="text-indigo-500" />
			<div className="tab-content container w-full">
				{ activeTab === 1 && <FeatureTab activeTab={activeTab} /> }
				{ activeTab === 2 && <FeatureTab activeTab={activeTab} /> }
				{ activeTab === 3 && <FeatureTab activeTab={activeTab} /> }
				{ activeTab === 4 && <FeatureTab activeTab={activeTab} /> }
				{ activeTab === 5 && <FeatureTab activeTab={activeTab} /> }
			</div>
		</div>
	);
}
