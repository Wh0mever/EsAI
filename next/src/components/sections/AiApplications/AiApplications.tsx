'use client';
import Radar from "@/components/global/Radar";
import { TextChangingTag } from "@/components/ui/text/Text";
import { useTranslation } from "next-i18next";

export default function AiApplications() {

	const { t } = useTranslation('home');

	return (
		<section className="px-30 py-10 section-divider">
			<div className="w-full flex flex-col items-center gap-4 py-20">
				<div className="px-4 py-2  bg-indigo-600/20 rounded-xl w-fit">
					<span>{t('aiapps.subtitle')}</span>
				</div>
				<h2 className="text-4xl font-bold">{t('aiapps.title')}</h2>
			</div>

			{/* grid cols */}
			<div className="grid grid-cols-3 relative">
				<div className="">
					<div className="flex flex-col items-center gap-4 p-4">
						<img src="/images/icons/google-fb-icon.webp" alt="" />
						<h5 className="text-xl font-bold">{t('aiapps.cards.0.title')}</h5>
						<p>{t('aiapps.cards.0.description')}</p>
					</div>
					<div className="flex flex-col items-center gap-4 p-4">
						<img src="/images/icons/icon-red.webp" alt="" />
						<h5 className="text-xl font-bold">{t('aiapps.cards.1.title')}</h5>
						<p>{t('aiapps.cards.1.description')}</p>
					</div>
				</div>
                <img src="/images/decorations/ai-application-shape-center.webp" alt="" className="absolute w-full left-0 top-0 -z-10" />
				<div className="relative flex items-center justify-center">
                    <div className="absolute top-0">
                        <TextChangingTag />
                    </div>
                    <Radar />
                </div>
				<div className="">
					<div className="flex flex-col items-center gap-4 p-4">
						<img src="/images/icons/store.webp" alt="" />
						<h5 className="text-xl font-bold">{t('aiapps.cards.2.title')}</h5>
						<p>{t('aiapps.cards.2.description')}</p>
					</div>
					<div className="flex flex-col items-center gap-4 p-4">
						<img src="/images/icons/store2.webp" alt="" />
						<h5 className="text-xl font-bold">{t('aiapps.cards.3.title')}</h5>
						<p>{t('aiapps.cards.3.description')}</p>
					</div>
				</div>
			</div>
		</section>
	);
}
