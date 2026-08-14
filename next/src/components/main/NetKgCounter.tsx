"use client";

import { useEffect, useState } from "react";

/** ID сайта esai.kg в рейтинге WWW.NET.KG (выдан вместе с кодом счётчика). */
const SITE_ID = "7522";

/**
 * NetKgCounter — счётчик посещаемости рейтинга WWW.NET.KG.
 *
 * Оригинальный код от net.kg вставить «как есть» нельзя, поэтому он
 * переписан один-в-один по смыслу, но безопасно для Next.js. Что изменено
 * и ПОЧЕМУ (важно при сверке с исходником):
 *
 * 1) document.write → обычный React-рендер. В SPA скрипт исполняется уже
 *    ПОСЛЕ загрузки документа, а document.write в этот момент затирает всю
 *    страницу целиком. Итоговый DOM (<a><img/></a>) тот же самый.
 *
 * 2) http:// → https://. Сайт работает по HTTPS, и картинка/ссылка по http
 *    считались бы смешанным контентом: браузер их блокирует, счётчик не
 *    засчитывал бы визиты. Проверено: https://www.net.kg/img.php отдаёт
 *    200 image/png, так что HTTPS у них поддерживается.
 *
 * 3) &amp; → &. В присланном коде параметры склеивались через &amp; (так
 *    он отображался на странице с инструкцией). Внутри <script> браузер
 *    HTML-сущности не раскрывает, поэтому в запрос уходило бы буквальное
 *    "&amp;page=" и параметры не разбирались бы на стороне net.kg.
 *
 * 4) Набор <script language="javascript1.1|1.2|1.3"> — способ 20-летней
 *    давности определять возможности браузера. Современные браузеры
 *    исполняют все блоки подряд, поэтому просто собираем итоговый набор
 *    параметров (jscript=1.3 — как в последнем блоке оригинала).
 *
 * Параметры сознательно считаются в useEffect, а не при рендере: они
 * зависят от window/screen/document.cookie, которых нет на сервере, а
 * Math.random() при SSR ломал бы гидратацию.
 */
export default function NetKgCounter() {
  const [imgSrc, setImgSrc] = useState<string | null>(null);

  useEffect(() => {
    try {
      // Оригинал ставит эту куку и потом проверяет, включены ли куки вообще.
      document.cookie = "astratop=1; path=/";

      const params = new URLSearchParams({
        refer: document.referrer,
        page: window.location.href,
        c: document.cookie ? "yes" : "now",
        java: navigator.javaEnabled?.() ? "yes" : "now",
        razresh: `${screen.width}x${screen.height}`,
        cvet: String(
          navigator.appName.substring(0, 3) === "Mic"
            ? (screen as Screen).colorDepth
            : (screen as Screen).pixelDepth
        ),
        jscript: "1.3",
        rand: String(Math.random()),
      });

      setImgSrc(`https://www.net.kg/img.php?id=${SITE_ID}&${params.toString()}`);
    } catch {
      // Счётчик — вспомогательная вещь: любая ошибка не должна ломать футер.
      // Показываем «голый» вариант без параметров, визит всё равно засчитается.
      setImgSrc(`https://www.net.kg/img.php?id=${SITE_ID}`);
    }
  }, []);

  return (
    <a
      href={`https://www.net.kg/stat.php?id=${SITE_ID}&fromsite=${SITE_ID}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="WWW.NET.KG"
      className="inline-block shrink-0"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {/* Картинку рендерим ТОЛЬКО когда готов финальный URL с параметрами.
          Если поставить запасной src сразу, браузер сходит на net.kg дважды
          (сначала за заглушкой, потом за настоящей) — и визит засчитается
          два раза, накручивая статистику.

          БЕЗ loading="lazy": именно запрос этой картинки и засчитывает визит.
          С ленивой загрузкой она грузилась бы только когда пользователь
          доскроллит до футера — большая часть посещений в рейтинг не попала бы. */}
      {imgSrc ? (
        <img src={imgSrc} alt="WWW.NET.KG" width={88} height={31} />
      ) : (
        // Держим место до готовности URL, чтобы футер не «прыгал».
        <span className="block" style={{ width: 88, height: 31 }} aria-hidden />
      )}
    </a>
  );
}
