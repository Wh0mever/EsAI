"use client";

import { FaFacebook, FaInstagram, FaTelegram } from "react-icons/fa";
import { FaXTwitter } from "react-icons/fa6";

import { useTranslation } from "react-i18next";

export default function Footer() {
  const { t } = useTranslation("home");

  return (
    <footer className="w-full border-t border-neutral-900">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 sm:py-14">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-6 items-center">
          <div className="flex flex-col gap-6 md:items-start items-center">
            <div className="flex items-center gap-6">
              <a
                href="https://www.facebook.com/share/19YGRrp4xw/?mibextid=wwXIfr"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-white/90 hover:text-white transition-colors"
                aria-label="Facebook"
              >
                <FaFacebook />
                <span className="hidden sm:inline">Facebook</span>
              </a>
              <a
                href="https://www.instagram.com/vokalo.online?igsh=MXh1MDd5OHc1YXV6aQ%3D%3D&utm_source=qr"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-white/90 hover:text-white transition-colors"
                aria-label="Instagram"
              >
                <FaInstagram />
                <span className="hidden sm:inline">Instagram</span>
              </a>
              <a
                href="https://t.me/vokaloonline"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-white/90 hover:text-white transition-colors"
                aria-label="Telegram"
              >
                <FaTelegram />
                <span className="hidden sm:inline">Telegram</span>
              </a>
              <a
                href="https://x.com/Vokaloonline"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-white/90 hover:text-white transition-colors"
                aria-label="X"
              >
                <FaXTwitter />
              </a>
            </div>

            <div className="flex items-center gap-4">
              <img src="/images/icons/footer_visa_el.webp" alt="Visa" className="h-9 sm:h-11 w-auto" />
            </div>
          </div>

          <div className="flex justify-center order-last md:order-none">
            <p className="text-xs text-white/40">© 2025 | Vokalo.online</p>
          </div>

          <nav className="flex md:justify-end justify-center">
            <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-white/70">
              <li>
                <a href="/about" className="hover:text-white transition-colors">
                  {t("nav.about")}
                </a>
              </li>
              <li>
                <a href="/contact-us" className="hover:text-white transition-colors">
                  {t("nav.contact")}
                </a>
              </li>
              <li>
                <a href="/privacy" className="hover:text-white transition-colors">
                  {t("nav.privacy")}
                </a>
              </li>
              <li>
                <a href="/terms-conditions" className="hover:text-white transition-colors">
                  {t("nav.terms")}
                </a>
              </li>
              <li>
                <a href="/offer" className="hover:text-white transition-colors">
                  {t("nav.offer")}
                </a>
              </li>
            </ul>
          </nav>
        </div>
      </div>
    </footer>
  );
}
