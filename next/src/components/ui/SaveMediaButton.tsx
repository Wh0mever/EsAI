"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { FiDownload, FiLoader } from "react-icons/fi";
import SaveSheet from "@/components/ui/SaveSheet";
import { WARM_MIN_RATIO, WARM_VISIBLE_MS } from "@/components/ui/saveWarm";
import { VS_BTN_GOLD, vx } from "@/components/vstudio/ui/skin";
import { trackFunnel } from "@/tools/funnel";
import { canWarmMedia, prefetchMedia, saveMedia, wantMedia, type SaveDiagMeta, type SheetStart } from "@/tools/saveMedia";

const reportSave = (meta: SaveDiagMeta) => trackFunnel("media_save", meta);

/**
 * Главная кнопка «Скачать» под результатом: тот же золотой вид, что у «Создать»
 * (VS_BTN_GOLD), но вдвое ниже — просьба клиента, серая иконка в строке действий
 * была незаметна. Вдвое по высоте: 22 px против 44. Шрифт 12 px, а не 7: половина
 * от 14 px не читается.
 *
 * vs-root — потому что кнопка стоит и вне студии (чат, страница ролика /v/), а цвета
 * золота заданы переменными только внутри .vs-root: без них у .vs-gold пропал бы фон.
 * Зона нажатия остаётся 44 px за счёт before: сама кнопка в строке не выше 22 px, а над
 * ней кадр с кнопками плеера, поэтому вверх зона не заходит дальше зазора.
 * Текст всегда рядом со значком, в том числе на телефоне: подпись и делает её заметной.
 */
export const SAVE_CTA = vx(
  "vs-root",
  VS_BTN_GOLD,
  "relative self-center whitespace-nowrap !h-[22px] !min-h-0 !gap-1 !px-2.5 !text-xs [&>svg]:size-3 [&>svg]:shrink-0",
  "before:absolute before:inset-x-0 before:-top-2.5 before:-bottom-3",
  "disabled:!opacity-80",
);

/**
 * Прогрев на iPhone: кнопка на экране не меньше половиной и не меньше секунды —
 * файл начинает качаться заранее, и первое нажатие сразу открывает системное окно.
 */
function useWarmMedia(button: RefObject<HTMLButtonElement | null>, url: string, enabled: boolean) {
  useEffect(() => {
    const el = button.current;
    if (!enabled || !el || !url || typeof IntersectionObserver === "undefined" || !canWarmMedia()) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let leave: (() => void) | null = null;
    const hide = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      leave?.();
      leave = null;
    };
    const observer = new IntersectionObserver(
      (records) => {
        const seen = records[records.length - 1];
        if (!seen?.isIntersecting || seen.intersectionRatio < WARM_MIN_RATIO) {
          hide();
        } else if (!timer && !leave) {
          timer = setTimeout(() => {
            timer = null;
            leave = wantMedia(url);
          }, WARM_VISIBLE_MS);
        }
      },
      { threshold: WARM_MIN_RATIO },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      hide();
    };
  }, [button, url, enabled]);
}

/**
 * SaveMediaButton — «Скачать» для картинок и видео, работающее на iPhone.
 *
 * Обычная ссылка с download на iOS не скачивает: WebKit просто уводит на файл и
 * показывает серую заглушку с иконкой MP4 и кнопкой «Открыть в iMovie». Поэтому
 * на телефоне файл сохраняется через нативный шитшет, а на компьютере — обычной
 * загрузкой файла (см. tools/saveMedia).
 *
 * На iPhone файл качается заранее, пока кнопка на экране (useWarmMedia), иначе —
 * на НАЖАТИЕ пальцем, а не на клик: iOS требует, чтобы системное окно
 * «Сохранить видео» открылось внутри пользовательского жеста.
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
  warm = true,
  children,
}: {
  url: string;
  filename: string;
  className?: string;
  iconClassName?: string;
  label?: string;
  /** Качать файл заранее на iPhone. Нет — на странице, куда приходят смотреть, а не сохранять. */
  warm?: boolean;
  children?: ReactNode;
}) {
  const [saving, setSaving] = useState(false);
  const [sheet, setSheet] = useState<SheetStart | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  useWarmMedia(buttonRef, url, warm);
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
