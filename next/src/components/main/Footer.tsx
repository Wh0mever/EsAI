"use client";

import { FaFacebook, FaInstagram, FaTelegram } from "react-icons/fa";
import { FaXTwitter } from "react-icons/fa6";
import { SiThreads } from "react-icons/si";

import { useTranslation } from "react-i18next";
import EsaiLogo from "@/components/brand/EsaiLogo";
import NetKgCounter from "@/components/main/NetKgCounter";
import { STUDIOS, TOOLS, MAIN_TAIL, COMPANY, LEGAL, type MenuItem } from "@/lib/nav/menu";

export default function Footer() {
  const { t } = useTranslation("home");
  const label = (i: MenuItem) => t(i.label, { ns: i.ns || "home", defaultValue: i.fallback });
  // Подвал — полная карта сайта: всё, что ушло из шапки (О нас, Контакты,
  // Помощь, Условия — решение клиента 16.11), плюс все студии и инструменты.
  const columns: { title: string; items: MenuItem[] }[] = [
    { title: t("nav.studios", { defaultValue: "Студии" }), items: STUDIOS },
    { title: t("nav.tools", { defaultValue: "Инструменты" }), items: TOOLS.filter((i) => !i.href.includes("?cat=")) },
    { title: t("nav.company", { defaultValue: "Компания" }), items: [...MAIN_TAIL, ...COMPANY] },
    { title: t("nav.legal", { defaultValue: "Документы" }), items: LEGAL },
  ];

  return (
    <footer className="w-full border-t border-border">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 sm:py-14">
        <nav aria-label={t("nav.more", { defaultValue: "Ещё" })} className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-8 pb-10 mb-10 border-b border-border">
          {columns.map((c) => (
            <div key={c.title}>
              <p className="text-xs uppercase tracking-wide text-muted-2 mb-3">{c.title}</p>
              <ul className="flex flex-col gap-2 text-sm text-muted">
                {c.items.map((i) => (
                  <li key={i.href + i.label}>
                    <a href={i.href} className="hover:text-foreground transition-colors">
                      {label(i)}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 md:gap-6 items-center">
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
              {/* Счётчик рейтинга WWW.NET.KG — нужен на каждой странице,
                  футер как раз общий для всех разделов сайта. */}
              <NetKgCounter />
            </div>
          </div>

          <div className="flex flex-col items-center md:items-end justify-center gap-2">
            <EsaiLogo className="h-7 w-auto" />
            <p className="text-xs text-muted-2">© 2026 | EsAI</p>
          </div>

        </div>
      </div>
    </footer>
  );
}
