/**
 * saveMedia — надёжное «Скачать» для картинок/видео: на телефоне — системное окно
 * «Сохранить видео/фото», на компьютере — обычный файл в «Загрузки».
 *
 * Телефоны и планшеты (iPhone, iPad, Android). В iOS <a download> ИГНОРИРУЕТСЯ
 * WebKit — ссылка уводит webview на файл и показывает «глушилку» (Quick Look-
 * предпросмотр). Поэтому там открываем НАТИВНЫЙ шитшет через Web Share API с файлом.
 *
 * Компьютер (в т.ч. Safari на macOS и Edge/Chrome на Windows): шитшет там тоже
 * «умеет файлы», но в нём нет пункта «Сохранить» — клиент отправлял сцену в
 * «Избранное» Telegram и получал только текст «esai-scene-1.mp4». Там — только
 * загрузка файла через <a download> из blob.
 *
 * Тонкость iOS: navigator.share({files}) требует «user activation» (жеста). Если
 * ПЕРЕД share долго тянуть файл через await fetch (видео 6–7 МБ), активация
 * истекает → iOS отклоняет шитшет и открывает тот самый предпросмотр. Поэтому
 * prefetchMedia() стартует загрузку заранее (на нажатие пальцем), чтобы к клику
 * файл был уже готов и share() вызвался почти без await.
 */

/** Что известно об устройстве — отдельно от navigator, чтобы выбор пути проверялся тестом. */
export type DeviceHints = {
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
  /** navigator.userAgentData.mobile (Chromium); нет — null. */
  uaMobile?: boolean | null;
};

/** share — системное окно, download — файл, open — открыть файл (старый iOS без файлового Share). */
export type SaveRoute = "share" | "download" | "open";

/** iPhone/iPod/iPad, включая iPadOS, который выдаёт себя за Mac, но с тачскрином. */
export function isAppleHandheld(h: DeviceHints): boolean {
  return /iP(hone|ad|od)/.test(h.userAgent) || (h.platform === "MacIntel" && h.maxTouchPoints > 1);
}

/**
 * Телефон или планшет. Ноутбук с сенсорным экраном — компьютер: тач у него есть,
 * а «мобильного» признака в user agent нет.
 */
export function isHandheld(h: DeviceHints): boolean {
  if (isAppleHandheld(h) || /Android/i.test(h.userAgent) || h.uaMobile === true) return true;
  return h.maxTouchPoints > 0 && /Mobi|Tablet|Silk|KFAPWI/i.test(h.userAgent);
}

/** Как сохранять: шитшет — только на телефоне/планшете, который умеет делиться файлом. */
export function pickSaveRoute(h: DeviceHints, canShareFile: boolean): SaveRoute {
  if (isHandheld(h) && canShareFile) return "share";
  // В iOS <a download> не скачивает — открываем файл, у предпросмотра есть «Поделиться».
  if (isAppleHandheld(h)) return "open";
  return "download";
}

type ShareNavigator = Navigator & {
  canShare?: (data?: ShareData) => boolean;
  userAgentData?: { mobile?: boolean };
};

function deviceHints(nav: ShareNavigator): DeviceHints {
  return {
    userAgent: nav.userAgent || "",
    platform: nav.platform || "",
    maxTouchPoints: nav.maxTouchPoints || 0,
    uaMobile: typeof nav.userAgentData?.mobile === "boolean" ? nav.userAgentData.mobile : null,
  };
}

// Гвард от повторных запусков по одному url: пока идёт сохранение, лишние тапы
// (пользователь думает «не жмётся») не плодят несколько шитшетов подряд.
const _inFlight = new Set<string>();

// Кэш начатых загрузок (prefetch): url → Promise<Blob>. Короткоживущий — чистится
// после сохранения, чтобы не держать мегабайты видео в памяти.
const _blobCache = new Map<string, Promise<Blob>>();

function _fetchBlob(url: string): Promise<Blob> {
  const p = fetch(url, { credentials: "omit" })
    .then((r) => r.blob())
    .catch((e) => {
      _blobCache.delete(url); // ошибку не кэшируем — дать возможность повтора
      throw e;
    });
  _blobCache.set(url, p);
  return p;
}

/** Начать загрузку файла заранее (вешать на onPointerDown кнопки «Скачать»). */
export function prefetchMedia(url: string): void {
  if (!url || _blobCache.has(url)) return;
  // Пустой catch — это лишь «прогрев», реальные ошибки обработает saveMedia.
  _fetchBlob(url).catch(() => {});
}

function downloadBlob(blob: Blob, filename: string): void {
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
}

export async function saveMedia(url: string, filename: string): Promise<void> {
  if (!url || _inFlight.has(url)) return;
  _inFlight.add(url);
  const nav = navigator as ShareNavigator;
  const hints = deviceHints(nav);
  try {
    // Берём заранее начатую загрузку (prefetch на pointerdown), иначе качаем сейчас.
    const blob = await (_blobCache.get(url) || _fetchBlob(url));
    const file = new File([blob], filename, {
      type: blob.type || "application/octet-stream",
    });

    // canShare спрашиваем только у телефона: на компьютере шитшет не нужен вовсе.
    const canShareFile =
      isHandheld(hints) &&
      typeof nav.share === "function" &&
      typeof nav.canShare === "function" &&
      nav.canShare({ files: [file] });
    const route = pickSaveRoute(hints, canShareFile);

    if (route === "share") {
      try {
        await nav.share({ files: [file], title: filename });
        return;
      } catch (e) {
        // Закрыл шитшет — это не ошибка, ничего не качаем.
        if ((e as { name?: unknown } | null)?.name === "AbortError") return;
        // Иначе — запасной путь ниже.
      }
    }

    if (route !== "open" && !isAppleHandheld(hints)) {
      downloadBlob(blob, filename);
      return;
    }

    // iOS без файлового Share (редкий старый случай): <a download> всё равно
    // игнорируется, поэтому просто открываем файл — в его предпросмотре снизу
    // есть кнопка «Поделиться» → «Сохранить видео».
    window.open(url, "_blank");
  } catch {
    window.open(url, "_blank");
  } finally {
    _inFlight.delete(url);
    _blobCache.delete(url); // освобождаем память (видео — несколько МБ)
  }
}
