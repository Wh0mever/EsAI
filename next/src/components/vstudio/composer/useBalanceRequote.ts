"use client";

/**
 * Видеостудия: баланс изменился — пора перепроверить цену.
 *
 * Остаток приходит вместе с ценой (quote), а тело запроса от оплаты не
 * меняется, поэтому сам пересчёт не срабатывает: человек пополнил баланс,
 * шапка показывает новую сумму, а кнопка всё ещё зовёт «Пополнить» и снова
 * открывает окно оплаты.
 *
 * Сигнал — событие окна balance:refresh: его шлют окна оплаты в момент
 * зачисления (QR, крипта, мгновенное пополнение) и закрытие окна пополнения.
 *
 * То же событие приходит после каждого запуска и закрытия дубля, поэтому
 * нужен ли перезапрос, решает сам onChange: только если по цене, которая
 * сейчас в руках, кредитов не хватало.
 */
import { useEffect, useLayoutEffect, useRef } from "react";

export const BALANCE_EVENT = "balance:refresh";

export function useBalanceRequote(onChange: () => void): void {
  const latest = useRef(onChange);
  useLayoutEffect(() => {
    latest.current = onChange;
  });
  useEffect(() => {
    const fire = () => latest.current();
    window.addEventListener(BALANCE_EVENT, fire);
    return () => window.removeEventListener(BALANCE_EVENT, fire);
  }, []);
}
