"use client";

import { FaFacebook, FaInstagram, FaTelegram } from "react-icons/fa";
import { FaXTwitter } from "react-icons/fa6";
import { SiThreads } from "react-icons/si";

import { useTranslation } from "react-i18next";
import EsaiLogo from "@/components/brand/EsaiLogo";

export default function Footer() {
  const { t } = useTranslation("home");

  return (
    <footer className="w-full border-t border-border">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 sm:py-14">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-6 items-center">
          <div className="flex flex-col gap-6 md:items-start items-center">
            <div className="flex items-center gap-6">
              <a
                href="https://www.instagram.com/esai.kg"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-foreground/90 hover:text-foreground transition-colors"
                aria-label="Instagram"
              >
                <FaInstagram />
                <span className="hidden sm:inline">Instagram</span>
              </a>
              <a
                href="https://t.me/EsAIkg"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-foreground/90 hover:text-foreground transition-colors"
                aria-label="Telegram"
              >
                <FaTelegram />
                <span className="hidden sm:inline">Telegram</span>
              </a>
              <a
                href="https://www.facebook.com/share/1EB2CnMbbj/?mibextid=wwXIfr"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-foreground/90 hover:text-foreground transition-colors"
                aria-label="Facebook"
              >
                <FaFacebook />
                <span className="hidden sm:inline">Facebook</span>
              </a>
              <a
                href="https://x.com/esaikg"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-foreground/90 hover:text-foreground transition-colors"
                aria-label="X (Twitter)"
              >
                <FaXTwitter />
              </a>
              <a
                href="https://www.threads.com/@esai.kg"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-foreground/90 hover:text-foreground transition-colors"
                aria-label="Threads"
              >
                <SiThreads />
              </a>
            </div>

            <div className="flex items-center gap-4">
              <img src="/images/icons/footer_visa_el.webp" alt="Visa" className="h-9 sm:h-11 w-auto" />
            </div>
          </div>

          <div className="flex flex-col items-center justify-center gap-2 order-last md:order-none">
            <EsaiLogo className="h-7 w-auto" />
            <p className="text-xs text-muted-2">© 2026 | EsAI</p>
          </div>

          <nav className="flex md:justify-end justify-center">
            <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
              <li>
                <a href="/about" className="hover:text-foreground transition-colors">
                  {t("nav.about")}
                </a>
              </li>
              <li>
                <a href="/contact-us" className="hover:text-foreground transition-colors">
                  {t("nav.contact")}
                </a>
              </li>
              <li>
                <a href="/privacy" className="hover:text-foreground transition-colors">
                  {t("nav.privacy")}
                </a>
              </li>
              <li>
                <a href="/terms-conditions" className="hover:text-foreground transition-colors">
                  {t("nav.terms")}
                </a>
              </li>
              <li>
                <a href="/public-offer" className="hover:text-foreground transition-colors">
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
