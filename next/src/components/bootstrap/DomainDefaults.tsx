"use client";

import { useEffect } from "react";
import { getOrCreateDeviceKey } from "@/tools/deviceKey";

/**
 * DomainDefaults — раньше синхронизировала ВАЛЮТУ по домену (принудительно
 * KGS + reload, единственная роль компонента: язык уже давно определяется
 * по браузеру, см. комментарий ниже). mapByHost() всегда возвращала "KGS" —
 * домен esai.kg один, так что реального ветвления не было никогда.
 *
 * Валюта теперь определяется точнее — по геолокации IP через бэкенд
 * (GET /api/plans/currency-rate/, suggested_currency), см.
 * next/src/hooks/useCurrency.ts. Та же гарантия приоритета ручного выбора
 * (APP_CURRENCY_MANUAL/APP_CURRENCY_SOURCE) сохранена внутри useCurrency() —
 * дублировать её здесь принудительным reload'ом на "KGS" больше нельзя: это
 * гонка, которая перетирала бы, например, RUB, определённый геолокацией из
 * России, обратно на KGS при каждой загрузке страницы.
 *
 * Компонент больше не no-op: он заводит ключ устройства. Место выбрано
 * потому, что смонтирован он на КАЖДОЙ странице, а ключ нужен уже к моменту
 * входа — в том числе при соц-входе, где страница успевает только уйти на
 * редирект (значение дублируется в cookie и доезжает вместе с ним).
 */
export default function DomainDefaults() {
  useEffect(() => {
    try {
      getOrCreateDeviceKey();
    } catch {}
  }, []);
  return null;
}
