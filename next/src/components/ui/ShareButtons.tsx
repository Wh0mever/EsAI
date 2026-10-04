"use client";

import { useState } from "react";
import { FaWhatsapp, FaTelegram, FaFacebookF, FaXTwitter, FaInstagram, FaVk } from "react-icons/fa6";
import { FiCheck, FiLink, FiShare2 } from "react-icons/fi";

/**
 * ShareButtons — плашки соцсетей под готовым роликом.
 *
 * Задача клиента: «пользователь должен легко скачать мультфильм или сразу
 * поделиться им — это важно для вирусного распространения Studio». Поэтому
 * кнопки заметные и подписанные, а не иконка «поделиться» где-то сбоку.
 *
 * Делимся ССЫЛКОЙ на нашу страницу ролика, а не файлом: страница несёт
 * og:video (мессенджеры играют ролик прямо в переписке) и, главное, призыв
 * «Создайте свой мультфильм» с переходом в студию. Отправь мы сам mp4 —
 * получился бы просто файл без единого упоминания EsAI.
 *
 * У Instagram нет веб-адреса для отправки ссылки: он принимает только
 * системный шитшет на телефоне. Поэтому его кнопка зовёт нативное «поделиться»
 * (там Instagram и появится в списке), а на десктопе честно копирует ссылку.
 */
export default function ShareButtons({
  url,
  text,
  compact = false,
  labels,
}: {
  url: string;
  /** Подпись, которая уедет вместе со ссылкой — в ней и живёт призыв. */
  text: string;
  compact?: boolean;
  /**
   * Подписи кнопок на языке страницы. Без них — русские, как было: студия
   * зовёт компонент без этого параметра.
   */
  labels?: { copy?: string; copied?: string; link?: string; more?: string };
}) {
  const [copied, setCopied] = useState(false);
  const copyLabel = labels?.copy ?? "Скопировать ссылку";
  const copiedLabel = labels?.copied ?? "Скопировано";
  const linkLabel = labels?.link ?? "Ссылка";
  const moreLabel = labels?.more ?? "Ещё";

  const enc = encodeURIComponent;
  const full = `${text} ${url}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Буфер недоступен (http или запрет) — ссылка и так на виду.
    }
  };

  const native = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ text, url });
        return;
      }
    } catch {
      // Пользователь закрыл системное окно — это не ошибка.
      return;
    }
    void copy();
  };

  const nets: {
    key: string;
    label: string;
    icon: React.ReactNode;
    color: string;
    href?: string;
    onClick?: () => void;
  }[] = [
    {
      key: "whatsapp",
      label: "WhatsApp",
      icon: <FaWhatsapp />,
      color: "bg-[#25D366]",
      href: `https://wa.me/?text=${enc(full)}`,
    },
    {
      key: "telegram",
      label: "Telegram",
      icon: <FaTelegram />,
      color: "bg-[#229ED9]",
      href: `https://t.me/share/url?url=${enc(url)}&text=${enc(text)}`,
    },
    {
      key: "instagram",
      label: "Instagram",
      icon: <FaInstagram />,
      color: "bg-gradient-to-br from-[#F58529] via-[#DD2A7B] to-[#8134AF]",
      onClick: () => void native(),
    },
    {
      key: "facebook",
      label: "Facebook",
      icon: <FaFacebookF />,
      color: "bg-[#1877F2]",
      href: `https://www.facebook.com/sharer/sharer.php?u=${enc(url)}`,
    },
    {
      key: "x",
      label: "X",
      icon: <FaXTwitter />,
      color: "bg-black",
      href: `https://twitter.com/intent/tweet?url=${enc(url)}&text=${enc(text)}`,
    },
    {
      key: "vk",
      label: "VK",
      icon: <FaVk />,
      color: "bg-[#0077FF]",
      href: `https://vk.com/share.php?url=${enc(url)}`,
    },
  ];

  const size = compact ? "h-10 w-10 text-lg" : "h-11 px-4 text-sm gap-2";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {nets.map((n) =>
        n.href ? (
          <a
            key={n.key}
            href={n.href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={n.label}
            title={n.label}
            className={`${n.color} ${size} inline-flex items-center justify-center rounded-xl font-semibold text-white transition-transform hover:scale-105 active:scale-95`}
          >
            <span className={compact ? "" : "text-lg"}>{n.icon}</span>
            {!compact && n.label}
          </a>
        ) : (
          <button
            key={n.key}
            type="button"
            onClick={n.onClick}
            aria-label={n.label}
            title={n.label}
            className={`${n.color} ${size} inline-flex cursor-pointer items-center justify-center rounded-xl font-semibold text-white transition-transform hover:scale-105 active:scale-95`}
          >
            <span className={compact ? "" : "text-lg"}>{n.icon}</span>
            {!compact && n.label}
          </button>
        )
      )}

      <button
        type="button"
        onClick={() => void copy()}
        className={`${size} inline-flex cursor-pointer items-center justify-center rounded-xl border border-border bg-surface font-semibold text-foreground transition-colors hover:border-accent`}
        title={copyLabel}
      >
        <span className={compact ? "" : "text-lg"}>
          {copied ? <FiCheck className="text-emerald-400" /> : <FiLink />}
        </span>
        {!compact && (copied ? copiedLabel : linkLabel)}
      </button>

      {/* Системное «поделиться» — на телефоне это самый короткий путь в любое
          приложение, включая те, у которых веб-ссылки для отправки нет. */}
      <button
        type="button"
        onClick={() => void native()}
        className={`${size} inline-flex cursor-pointer items-center justify-center rounded-xl border border-border bg-surface font-semibold text-foreground transition-colors hover:border-accent sm:hidden`}
        title={moreLabel}
      >
        <span className={compact ? "" : "text-lg"}>
          <FiShare2 />
        </span>
        {!compact && moreLabel}
      </button>
    </div>
  );
}
