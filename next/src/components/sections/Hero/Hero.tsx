'use client'

import './Hero.scss';
import { Button } from "@/components/ui/buttons/Buttons";
import NextLink from '@/components/ui/nextLink/NextLink';
import { IoIosArrowRoundForward } from "react-icons/io";
import {TextChanging} from "@/components/ui/text/Text"
import { useTranslation } from "react-i18next";

export default function SectionHero() {
	const { t } = useTranslation('home');
	const title = t("hero.title");
	const subtitle = t("hero.subtitle");
	const buttonText = t("hero.button");

	return (
		<section className="hero relative w-full py-40 px-20 mx-auto text-center flex flex-col gap-7 items-center">
            <div className="absolute top-0 flex justify-center hero-top">
                <img src="/images/decorations/hero-top-line.webp" alt="" className="absolute z-20 max-w-max" />
                <img src="/images/decorations/hero-top-dots.webp" alt="" className="absolute z-10 max-w-max" />
            </div>

			<div className="hero-circle">
				<div className="hero-circle-left"></div>
				<div className="hero-circle-right"></div>
			</div>

			<h1 className="text-5xl font-bold text-center">{`${title}`}</h1>
			<TextChanging />
			<p className="text-md">{`${subtitle}`}</p>

			<NextLink
				href={'/auth/signup'}
				className="bg-indigo-500 w-fit px-5 py-3 rounded-lg text-lg hover:bg-indigo-600 flex items-center gap-1"
			>
				<span>{`${buttonText}`}</span>
				<IoIosArrowRoundForward className="text-xl" />
			</NextLink>

			<div className="w-6/12 min-w-[250px] border-18 rounded-2xl mt-2 border-neutral-800">
				<video src="/video/wirtebot-video.mp4" autoPlay muted loop></video>
			</div>
		</section>
	);
}
