'use client';

import './AiTools.scss';
import { FaFacebookF } from "react-icons/fa";
import { BsStars } from "react-icons/bs";
import { PiLockKeyBold } from "react-icons/pi";
import { TextTag } from '@/components/ui/text/Text';
import { useTranslation } from 'react-i18next';

export default function AiTools() {

	const { t } = useTranslation('home');
	const title = t("aiTools.title");
	const subtitle = t("aiTools.subtitle");
	

	return (
		<section className="px-10 py-20 lg:px-30 lg:py-30 section-divider">
			<div className="">
				<div className="text-center mb-12 relative flex flex-col items-center justify-center gap-5">
					<TextTag text={subtitle} />
					<div className="mt-2 relative">
                        <h2 className="text-3xl font-semibold">{title}</h2>
                    </div>
				</div>

				<div className="grid gap-8 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
					{/* 0-1 */}
					<div className="flex flex-col gap-5">
						<div className="bg-neutral-800/20 hover:bg-neutral-800/50 transition-colors duration-300 rounded-xl p-10 flex flex-col items-center text-center border border-neutral-800">
							<div className="flex gap-4 mb-4">
								<button className="bg-neutral-800 p-2 rounded-full">
									<BsStars />
								</button>
								<button className="bg-neutral-800 p-2 rounded-full">
									<FaFacebookF />
								</button>
							</div>
							<p className="text-sm text-gray-300">
								{t("aiTools.cards.0.description")}
							</p>
						</div>
						<div className="bg-neutral-800/20 hover:bg-neutral-800/50 transition-colors duration-300 rounded-xl p-10 text-center border border-neutral-800 flex flex-col items-center gap-5">
							<div className="mb-4">
								<img src="/images/aitools/4.webp" alt="График" className="" />
							</div>
							<h3 className="font-semibold text-lg mb-2">{t("aiTools.cards.1.title")}</h3>
							<p className="text-sm text-gray-300">{t("aiTools.cards.1.description")}</p>
						</div>
					</div>
					{/* 2 */}
					<div className="flex flex-col gap-5">
						<div className="bg-neutral-800/20 hover:bg-neutral-800/50 transition-colors duration-300 rounded-xl p-10 text-center border border-neutral-800 flex flex-col items-center gap-5">
							<div className="mb-4">
								<img src="/images/aitools/2.webp" alt="Многоязычная поддержка" className="" />
							</div>
							<h3 className="font-semibold text-lg mb-2">{t("aiTools.cards.2.title")}</h3>
							<p className="text-sm text-gray-300">
								{t("aiTools.cards.2.description")}
							</p>
						</div>
					</div>
					{/* 3-4 */}
					<div className="flex flex-col gap-5">
						<div className="bg-neutral-800/20 hover:bg-neutral-800/50 transition-colors duration-300 rounded-xl p-10 text-center border border-neutral-800 flex flex-col items-center gap-5">
							<img src="/images/aitools/3.webp" alt="" />
							<h3 className="font-semibold text-lg mb-2">{t("aiTools.cards.3.title")}</h3>
							<p className="text-sm text-gray-300">{t("aiTools.cards.3.description")}</p>
						</div>
						<div className="bg-neutral-800/20 hover:bg-neutral-800/50 transition-colors duration-300 rounded-xl p-10 text-center border border-neutral-800">
							<div className="text-3xl mb-4 mx-auto w-12 h-12 bg-neutral-800 rounded-full flex items-center justify-center">
								<PiLockKeyBold />
							</div>
							<h3 className="font-semibold text-lg mb-2">{t("aiTools.cards.4.title")}</h3>
							<p className="text-sm text-gray-300">
								{t("aiTools.cards.4.description")}
							</p>
						</div>
					</div>
				</div>
			</div>

			<div className="w-full h-full absolute top-0 left-0 z-[-1] pointer-events-none">
				<img src="/images/decorations/ai-tools-shape-left-start.webp" alt="" className="absolute left-0 top-0" />
				<img src="/images/decorations/ai-tools-shape-left.webp" alt="" className="absolute left-0 top-0" />
				<img src="/images/decorations/ai-tools-shape-right-start.webp" alt="" className="absolute right-0 top-0" />
				<img src="/images/decorations/ai-tools-shape-top-right.webp" alt="" className="absolute right-0 top-0" />
			</div>
		</section>
	);
}
