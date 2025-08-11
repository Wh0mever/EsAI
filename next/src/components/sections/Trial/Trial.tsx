'use client';
import { TextTag } from "@/components/ui/text/Text";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { useTranslation } from "next-i18next";

export default function Trial() {

	const { t } = useTranslation('home');

	return (
		<section className="px-30 py-20 relative flex flex-col justify-center items-center">
			<img src="/images/decorations/cta-4-bg.webp" alt="" className="" />
			<div className="flex flex-col gap-5 absolute justify-center items-center">
				<TextTag text={t('trial.subtitle')} />

				<h2 className="text-5xl font-bold text-center">
					{t('trial.title')}
				</h2>

				<p className="text-sm text-gray-400">{t('trial.text')}.</p>

				<ul className="flex gap-3">
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
