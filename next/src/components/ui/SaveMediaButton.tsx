"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";
import { FiDownload, FiLoader } from "react-icons/fi";
import SaveSheet from "@/components/ui/SaveSheet";
import { trackFunnel } from "@/tools/funnel";
import { prefetchMedia, saveMedia, type SaveDiagMeta, type SheetStart } from "@/tools/saveMedia";

const reportSave = (meta: SaveDiagMeta) => trackFunnel("media_save", meta);

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
 * Не успел тяжёлый ролик, окно отказало или его нет (встроенный браузер) —
 * открывается шторка SaveSheet: файл догружается в ней, и следующий шаг
 * человек делает там, а не на тёмной странице с самим файлом.
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
  const [sheet, setSheet] = useState<SheetStart | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const closeSheet = useCallback(() => {
    setSheet(null);
    buttonRef.current?.focus();
  }, []);

  return (
    <>
      <button
        ref={buttonRef}
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
          void saveMedia(url, filename, { report: reportSave })
            .then((outcome) => {
              if (outcome.result === "sheet") setSheet(outcome.sheet);
            })
            .finally(() => setSaving(false));
        }}
        className={`${className || ""} disabled:opacity-70 disabled:cursor-wait`}
      >
        {saving ? (
          <FiLoader className={`${iconClassName || ""} animate-spin motion-reduce:animate-none`} />
        ) : (
          <FiDownload className={iconClassName} />
        )}
        {children}
      </button>
      {sheet && <SaveSheet url={url} filename={filename} start={sheet} onClose={closeSheet} />}
    </>
  );
}
