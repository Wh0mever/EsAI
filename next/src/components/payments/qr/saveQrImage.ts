import type { QrEmbed, QrPlatform } from "@/lib/qrpay";

/**
 * «Сохранить QR-код» — картинкой, которую приложение банка умеет загрузить
 * («Оплата по QR» → «Из галереи»).
 *
 * Общий tools/saveMedia.ts сюда не годится: он предпочитает navigator.share
 * везде, где тот умеет файлы (Android Chrome, настольный Chrome и Edge), — и
 * «сохранить» открывало бы окно «поделиться» без пункта «в галерею». К тому же
 * он глотает любые ошибки, и запасной путь никогда бы не сработал.
 *
 * Возвращает true, если файл ушёл человеку (или он сам закрыл окно
 * сохранения), false — если сохранить не вышло: тогда экран честно говорит
 * об этом и даёт ссылку на картинку.
 */

const SIZE = 1024;
// Белые поля вокруг кода: без «тихой зоны» сканеры банков код не читают.
const MARGIN = 64;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("qr image load failed"));
    img.src = src;
  });
}

/** Нарисованный на экране SVG → PNG 1024×1024 на белом фоне. null — не вышло. */
export async function renderQrPng(wrapper: HTMLElement | null): Promise<Blob | null> {
  try {
    const svg = wrapper?.querySelector("svg");
    if (!svg) return null;
    const inner = SIZE - MARGIN * 2;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    // Safari рисует SVG на canvas только с явными размерами; заодно растр
    // получается сразу в нужном размере, без размытия при растягивании.
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", String(inner));
    clone.setAttribute("height", String(inner));
    clone.removeAttribute("style");
    const xml = new XMLSerializer().serializeToString(clone);
    const img = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`);

    const canvas = document.createElement("canvas");
    canvas.width = SIZE;
    canvas.height = SIZE;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, MARGIN, MARGIN, inner, inner);
    return await new Promise<Blob | null>((resolve) => {
      try {
        canvas.toBlob((blob) => resolve(blob), "image/png");
      } catch {
        resolve(null);
      }
    });
  } catch {
    return null;
  }
}

/**
 * prepared — PNG, отрисованный заранее. На iOS окно «сохранить» открывается
 * только по живому нажатию: если между нажатием и share() ждать отрисовку,
 * Safari может счесть, что жеста уже не было.
 */
export async function saveQrImage(
  wrapper: HTMLElement | null,
  filename: string,
  platform: QrPlatform,
  embed: QrEmbed,
  prepared?: Blob | null
): Promise<boolean> {
  try {
    const blob = prepared || (await renderQrPng(wrapper));
    if (!blob) return false;

    // Встроенные браузеры (Telegram, Instagram, Facebook): ни «поделиться
    // файлом», ни скачивание blob там не работают — молчаливое «ничего».
    if (embed !== "browser") return false;

    if (platform === "ios") {
      // <a download> в iOS уводит страницу на картинку. Нужное окно —
      // системное, в нём есть «Сохранить изображение».
      const file = new File([blob], filename, { type: "image/png" });
      const nav = navigator as Navigator & { canShare?: (data?: ShareData) => boolean };
      if (typeof nav.share !== "function" || !nav.canShare?.({ files: [file] })) return false;
      try {
        await nav.share({ files: [file] });
        return true;
      } catch (e) {
        // Человек сам закрыл окно — это не сбой.
        return (e as { name?: string } | null)?.name === "AbortError";
      }
    }

    // Android и компьютер: обычное скачивание. Файл попадает в «Загрузки»,
    // а их показывают и галерея, и выбор файла в приложениях банков.
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.rel = "noopener";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => {
      try {
        URL.revokeObjectURL(url);
      } catch {
        // уже отозван — не страшно
      }
    }, 10000);
    return true;
  } catch {
    return false;
  }
}
