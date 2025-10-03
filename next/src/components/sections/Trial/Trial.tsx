'use client';
import { TextTag } from "@/components/ui/text/Text";
import { IoIosCheckmark } from "react-icons/io";
import { useTranslation } from "next-i18next";

export default function Trial() {

	const { t } = useTranslation('home');

	return (
		<section className="mt-20 relative overflow-hidden flex items-center justify-center px-6 sm:px-10 min-h-screen py-16 md:py-24 lg:py-28">
			{/* Decorative background image: full-bleed, no layout shift on mobile */}
			<img
				src="/images/decorations/cta-4-bg.webp"
				alt=""
				aria-hidden="true"
				className="absolute inset-0 -z-10 w-full h-full object-cover select-none pointer-events-none"
			/>
			<div className="relative z-10 flex flex-col items-center justify-center gap-5 px-4 sm:px-6 py-10 text-center max-w-4xl">
				<TextTag text={t('trial.subtitle')} />

				<h2 className="text-3xl font-bold text-center">
					{t('trial.title')}
				</h2>

				<p className="text-sm text-gray-400 text-center">{t('trial.text')}.</p>

				<ul className="flex gap-3 flex-wrap justify-center py-5 px-2">
					<li className="flex gap-2 items-center">
						<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
							<IoIosCheckmark />
						</i>
						<span>{t('trial.items.0')}</span>
					</li>
					<li className="flex gap-2 items-center">
						<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
							<IoIosCheckmark />
						</i>
						<span>{t('trial.items.1')}</span>
					</li>
					<li className="flex gap-2 items-center">
						<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
							<IoIosCheckmark />
						</i>
						<span>{t('trial.items.2')}</span>
					</li>
					<li className="flex gap-2 items-center">
						<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
							<IoIosCheckmark />
						</i>
						<span>{t('trial.items.3')}</span>
					</li>
				</ul>
			</div>
		</section>
	);
}
