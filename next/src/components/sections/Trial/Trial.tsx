'use client';
import { TextTag } from "@/components/ui/text/Text";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { useTranslation } from "next-i18next";

export default function Trial() {

	const { t } = useTranslation('home');

	return (
		<section className="px-10 py-20 mt-20 lg:px-30 lg:py-30 relative flex flex-col justify-center items-center overflow-hidden">
			{/* Decorative background image: full-bleed, no layout shift on mobile */}
			<img
				src="/images/decorations/cta-4-bg.webp"
				alt=""
				aria-hidden="true"
				className="absolute inset-0 -z-10 w-full h-full object-cover select-none pointer-events-none"
			/>
			<div className="flex flex-col px-2 gap-5 absolute inset-0 justify-center items-center py-10">
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
