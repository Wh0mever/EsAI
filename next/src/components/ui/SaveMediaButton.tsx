"use client";

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiDownload, FiLoader } from "react-icons/fi";
import { prefetchMedia, saveMedia } from "@/tools/saveMedia";

/**
 * SaveMediaButton — «Скачать» для картинок и видео, работающее на iPhone.
 *
 * Обычная ссылка с download на iOS не скачивает: WebKit просто уводит на файл и
 * показывает серую заглушку с иконкой MP4 и кнопкой «Открыть в iMovie». Поэтому
 * на телефоне файл сохраняется через нативный шитшет, а на компьютере — обычной
 * загрузкой файла (см. tools/saveMedia).
 *
 * Загрузка стартует на НАЖАТИЕ пальцем, а не на клик: iOS требует, чтобы
 * системное окно «Сохранить видео» открылось внутри пользовательского жеста.
 * Тяжёлый ролик (видеостудия) за это время может не успеть скачаться — тогда iOS
 * окно не открывает, а кнопка становится «Сохранить»: файл уже в памяти, и второе
 * нажатие открывает окно сразу.
 *
 * Пока идёт сохранение, кнопка заблокирована: без этого человек, думая, что
 * «не жмётся», тапал ещё раз, и шитшетов выскакивало несколько подряд.
 */
export default function SaveMediaButton({
  url,
  filename,
  className,
  iconClassName,
  label,
  children,
}: {
  url: string;
  filename: string;
  className?: string;
  iconClassName?: string;
  label?: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation("common");
  const [saving, setSaving] = useState(false);
  const [again, setAgain] = useState(false);
  const againLabel = t("media.save_again", { defaultValue: "Сохранить" });

  return (
    <button
      type="button"
      disabled={saving}
      aria-busy={saving}
      aria-label={again ? againLabel : label}
      title={again ? againLabel : label}
      onPointerDown={() => prefetchMedia(url)}
      onClick={(e) => {
        e.stopPropagation();
        if (saving) return;
        setSaving(true);
        void saveMedia(url, filename)
          .then((result) => setAgain(result === "retry"))
          .finally(() => setSaving(false));
      }}
      className={`${className || ""} disabled:opacity-70 disabled:cursor-wait ${
        again ? "!text-accent ring-1 ring-accent/60 rounded-full animate-pulse" : ""
      }`}
    >
      {saving ? (
        <FiLoader className={`${iconClassName || ""} animate-spin`} />
      ) : again ? (
        <FiCheck className={iconClassName} />
      ) : (
        <FiDownload className={iconClassName} />
      )}
      {again ? <span>{againLabel}</span> : children}
    </button>
  );
}
