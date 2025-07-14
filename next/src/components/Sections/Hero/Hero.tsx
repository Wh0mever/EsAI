'use client'

import './Hero.scss';
import { Button } from "@/components/UI/Buttons/Buttons";
import { IoIosArrowRoundForward } from "react-icons/io";
import {TextChanging} from "@/components/UI/Text/Text"
import { useTranslation } from "react-i18next";

export default function SectionHero() {
	const { t } = useTranslation('home');
	const title = t("hero.title");
	const subtitle = t("hero.subtitle");
	const buttonText = t("hero.button");

	return (
		<section className="hero py-50 antialiased container mx-auto px-10 text-center flex flex-col gap-7 items-center">
            <div className="absolute top-0 flex justify-center hero-top">
                <img src="/images/decorations/hero-top-line.webp" alt="" className="absolute z-20 max-w-max" />
                <img src="/images/decorations/hero-top-dots.webp" alt="" className="absolute z-10 max-w-max" />
            </div>

			<div className="hero-circle">
				<div className="hero-circle-left"></div>
				<div className="hero-circle-right"></div>
			</div>

			<h1 className="text-6xl font-bold">{`${title}`}</h1>
			<TextChanging />
			<p className="text-md">{`${subtitle}`}</p>

			<Button
				onClick={() => {}}
				className="bg-indigo-500 w-fit px-5 py-3 rounded-lg text-lg hover:bg-indigo-600 flex items-center gap-1"
			>
				<span>{`${buttonText}`}</span>
				<IoIosArrowRoundForward className="text-xl" />
			</Button>

			<div className="w-6/12 border-18 rounded-2xl mt-2 border-neutral-800">
				<video src="/video/wirtebot-video.mp4" autoPlay muted loop></video>
			</div>
		</section>
	);
}
