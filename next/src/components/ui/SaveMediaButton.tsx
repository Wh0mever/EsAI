"use client";

import { useState, type ReactNode } from "react";
import { FiDownload, FiLoader } from "react-icons/fi";
import { prefetchMedia, saveMedia } from "@/tools/saveMedia";

/**
 * SaveMediaButton — «Скачать» для картинок и видео, работающее на iPhone.
 *
 * Обычная ссылка с download на iOS не скачивает: WebKit просто уводит на файл и
 * показывает серую заглушку с иконкой MP4 и кнопкой «Открыть в iMovie». Поэтому
 * файл сохраняется через нативный шитшет (см. tools/saveMedia).
 *
 * Загрузка стартует на НАЖАТИЕ пальцем, а не на клик: iOS требует, чтобы
 * системное окно «Сохранить видео» открылось внутри пользовательского жеста, а
 * шестимегабайтный ролик за это время не успевает скачаться. К моменту клика
 * файл уже готов, и окно успевает открыться.
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
  const [saving, setSaving] = useState(false);

  return (
    <button
      type="button"
      disabled={saving}
      aria-busy={saving}
      aria-label={label}
      title={label}
      onPointerDown={() => prefetchMedia(url)}
      onClick={(e) => {
        e.stopPropagation();
        if (saving) return;
        setSaving(true);
        void saveMedia(url, filename).finally(() => setSaving(false));
      }}
      className={`${className || ""} disabled:opacity-70 disabled:cursor-wait`}
    >
      {saving ? (
        <FiLoader className={`${iconClassName || ""} animate-spin`} />
      ) : (
        <FiDownload className={iconClassName} />
      )}
      {children}
    </button>
  );
}
