import type { Metadata } from "next";
import { parseSaveTarget } from "@/tools/saveEnv";
import SaveClient from "./SaveClient";

/**
 * /save?f=/media/…&n=<имя> — «Сохранить видео» без входа.
 *
 * Встроенный браузер Telegram или Instagram на iPhone не умеет сохранить видео в
 * «Фото», а «Открыть в Safari» уводит в Safari со своей, пустой сессией: студия
 * там гостевая, ролика не видно. Шторка «Сохранить» копирует ссылку сюда — эта
 * страница показывает сам файл и ту же кнопку, вход ей не нужен. Файл по такой
 * ссылке публичен ровно настолько же, насколько публичен сам /media/… (имя не
 * угадать).
 *
 * Принимается только наш /media/ (parseSaveTarget): ни чужого адреса, ни
 * открытого редиректа.
 *
 * Поисковику страница не нужна — noindex в метаданных. В robots.txt её НЕ
 * закрываем: закрытую там страницу робот не скачивает, noindex не видит и может
 * оставить адрес в выдаче по внешним ссылкам.
 *
 * Адрес страницы (с путём к файлу) не уходит дальше: Метрики и gtag здесь нет
 * (корневой layout), а referrer со страницы — только origin, иначе следующая
 * страница сайта передала бы его счётчикам в document.referrer.
 */
export const metadata: Metadata = {
  title: "Сохранить файл — EsAI",
  robots: { index: false, follow: false },
  referrer: "origin",
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function SavePage({ searchParams }: { searchParams: SearchParams }) {
  const sp = await searchParams;
  return <SaveClient target={parseSaveTarget(sp.f, sp.n)} />;
}
