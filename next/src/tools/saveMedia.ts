/**
 * saveMedia — надёжное «Скачать» для картинок/видео, работающее в установленном PWA (iOS).
 *
 * Проблема: в iOS <a download> ИГНОРИРУЕТСЯ WebKit — ссылка уводит webview на файл
 * и показывает «глушилку» (Quick Look-предпросмотр). Нужно вместо этого открыть
 * НАТИВНЫЙ шитшет «Сохранить видео/фото» через Web Share API с файлом.
 *
 * Тонкость iOS: navigator.share({files}) требует «user activation» (жеста). Если
 * ПЕРЕД share долго тянуть файл через await fetch (видео 6–7 МБ), активация
 * истекает → iOS отклоняет шитшет и открывает тот самый предпросмотр. Поэтому:
 *   1) prefetchMedia() стартует загрузку заранее (на нажатие пальцем), чтобы к
 *      клику файл был уже готов и share() вызвался почти без await;
 *   2) share пробуем ВСЕГДА, когда браузер умеет делиться файлами (не завязываясь
 *      на display-mode — раньше гейт standalone мог не сработать);
 *   3) на iOS НЕ используем <a download> вообще (он и есть источник «глушилки»).
 */

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

function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  // iPhone/iPod/iPad + iPadOS (маскируется под Mac, но с тач-экраном).
  return (
    /iP(hone|ad|od)/.test(ua) ||
    (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1)
  );
}

export async function saveMedia(url: string, filename: string): Promise<void> {
  if (!url || _inFlight.has(url)) return;
  _inFlight.add(url);
  try {
    // Берём заранее начатую загрузку (prefetch на pointerdown), иначе качаем сейчас.
    const blob = await (_blobCache.get(url) || _fetchBlob(url));
    const file = new File([blob], filename, {
      type: blob.type || "application/octet-stream",
    });

    // Web Share с файлом = нативный шитшет «Сохранить видео/фото». Работает и в
    // iOS Safari, и в установленном PWA. Пробуем всегда, когда поддерживается.
    const nav = navigator as any;
    if (typeof nav.canShare === "function" && nav.canShare({ files: [file] })) {
      try {
        await nav.share({ files: [file], title: filename });
        return;
      } catch (e) {
        // Закрыл шитшет — это не ошибка, ничего не качаем.
        if ((e as any)?.name === "AbortError") return;
        // Иначе — проваливаемся в фолбэк ниже.
      }
    }

    // Не-iOS (десктоп/Android): обычное скачивание в файл.
    if (!isIOS()) {
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
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
