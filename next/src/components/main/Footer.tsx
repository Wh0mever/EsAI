'use client';

import { FaFacebook, FaInstagram } from "react-icons/fa";
import { useTranslation } from "react-i18next";

export default function Footer() {

	const { t } = useTranslation('home');

	return (
		<footer className="border-t border-neutral-900 w-full grid grid-cols-3 px-30 py-20">
			<div className="flex flex-col gap-5 justify-center items-start">
				<div className="flex items-center gap-5">
					<div className="flex items-center gap-3 text-sm text-white/90">
						<FaFacebook />
						Facebook
					</div>
					<div className="flex items-center gap-3 text-sm text-white/90">
						<FaInstagram />
						Instagram
					</div>
				</div>

				<div className="flex items-center gap-4 mt-4 sm:mt-0">
					<img src="/images/icons/footer_visa_el.webp" alt="Visa" className="h-11" />
				</div>
			</div>
			<div className="flex items-center justify-center">
				<p className="text-xs text-white/40 mt-5">© 2025 | Vokalo.online</p>
			</div>
			<div className="flex items-end justify-center">
				<div className="flex flex-wrap justify-end gap-5 text-sm text-white/70 mt-10">
					<a href="/about">{t('nav.about')}</a>
					<a href="/contact-us">{t('nav.contact')}</a>
					<a href="/">{t('nav.privacy')}</a>
					<a href="/terms-conditions">{t('nav.terms')}</a>
					<a href="#">{t('nav.offer')}</a>
				</div>
			</div>
		</footer>
	);
}
