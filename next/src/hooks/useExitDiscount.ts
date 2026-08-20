"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { fetchData } from "@/tools/fetchData";
// Ключ устройства общий на весь сайт (вход, скидка, блокировки) — см. tools/deviceKey.
import { getOrCreateDeviceKey } from "@/tools/deviceKey";


const ENDPOINT = {
  status: "plans/exit-discount/status/",
  show: "plans/exit-discount/show/",
  claim: "plans/exit-discount/claim/",
  dismiss: "plans/exit-discount/dismiss/",
} as const;

export type ExitDiscountOffer = {
  percent: number;
  expires_at: string;
};

type StatusResponse = {
  eligible_for_popup: boolean;
  active: (ExitDiscountOffer & { seconds_left?: number }) | null;
};

function isTouchDevice(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return true;
  } catch {}
  return "ontouchstart" in window;
}

/**
 * useExitDiscount — попап скидки при попытке уйти со страницы /pricing.
 *
 * Десктоп: ловим mouseleave на document, когда курсор уходит вверх за пределы
 * окна (e.clientY <= 0) — классический exit-intent.
 * Мобайл: перехватываем системный "назад" через history.pushState/popstate —
 * при popstate возвращаем URL на место (не даём уйти) и показываем попап.
 *
 * Осознанное ограничение: сворачивание вкладки/приложения НЕ ловится — нет
 * надёжного кросс-платформенного способа показать НОВЫЙ модал уже после того,
 * как вкладка ушла в фон (visibilitychange срабатывает, но открывать модалку
 * в этот момент браузеры блокируют/игнорируют, а показывать её из фона к
 * моменту возврата пользователя — уже не exit-intent, а обычный интерстишл).
 * Это не баг, это платформенное ограничение.
 */
export function useExitDiscount(paymentInProgress: boolean = false) {
  const pathname = usePathname();
  const onPricingPage = pathname === "/pricing";

  const [deviceKey, setDeviceKey] = useState("");
  const [eligible, setEligible] = useState(false);
  const [active, setActive] = useState<ExitDiscountOffer | null>(null);
  const [showPopup, setShowPopup] = useState(false);
  const [popupOffer, setPopupOffer] = useState<ExitDiscountOffer | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const triggeredRef = useRef(false);
  const historyArmedRef = useRef(false);

  useEffect(() => {
    setDeviceKey(getOrCreateDeviceKey());
  }, []);

  // Начальный статус — только на /pricing и только когда есть device key.
  useEffect(() => {
    if (!onPricingPage || !deviceKey) return;
    let cancelled = false;
    (async () => {
      const res = await fetchData<StatusResponse>(ENDPOINT.status, "GET", null, true, {
        "X-Device-Key": deviceKey,
      });
      if (cancelled) return;
      if (res.ok && res.data) {
        setEligible(Boolean(res.data.eligible_for_popup));
        if (res.data.active) {
          setActive({ percent: res.data.active.percent, expires_at: res.data.active.expires_at });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onPricingPage, deviceKey]);

  const onExitTrigger = useCallback(async () => {
    if (triggeredRef.current || !deviceKey) return;
    triggeredRef.current = true;
    const res = await fetchData<ExitDiscountOffer>(
      ENDPOINT.show,
      "POST",
      { device_key: deviceKey },
      true,
      { "X-Device-Key": deviceKey }
    );
    if (res.ok && res.data) {
      setPopupOffer({ percent: res.data.percent, expires_at: res.data.expires_at });
      setShowPopup(true);
    } else {
      // Сетевой сбой/таймаут/не-2xx — попап так и не показан пользователю.
      // Не оставляем triggeredRef навсегда "true": следующая попытка выхода
      // (повторный mouseleave/back) должна суметь повторить запрос, а не
      // молча ничего не делать до конца жизни компонента.
      triggeredRef.current = false;
    }
  }, [deviceKey]);

  // Вооружение слушателей exit-intent.
  useEffect(() => {
    if (!onPricingPage || !eligible || paymentInProgress || !deviceKey) return;
    if (triggeredRef.current) return;

    const touch = isTouchDevice();

    if (!touch) {
      const onMouseLeave = (e: MouseEvent) => {
        // Не отписываемся сразу: onExitTrigger сам гейтится triggeredRef и
        // сбрасывает его при сетевом сбое — так следующий mouseleave может
        // повторить попытку вместо того, чтобы навсегда остаться без попапа.
        if (e.clientY <= 0) {
          onExitTrigger();
        }
      };
      document.addEventListener("mouseleave", onMouseLeave);
      return () => document.removeEventListener("mouseleave", onMouseLeave);
    }

    // Мобайл: перехват "назад".
    if (!historyArmedRef.current) {
      historyArmedRef.current = true;
      try {
        window.history.pushState(null, "", window.location.href);
      } catch {}
    }

    const onPopState = () => {
      if (triggeredRef.current) return;
      try {
        window.history.pushState(null, "", window.location.href);
      } catch {}
      // Не отписываемся сразу — см. комментарий у onMouseLeave: даёт шанс на
      // повторную попытку после сетевого сбоя вместо permanent-latch.
      onExitTrigger();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [onPricingPage, eligible, paymentInProgress, deviceKey, onExitTrigger]);

  const claim = useCallback(async () => {
    if (!deviceKey) return null;
    const res = await fetchData<ExitDiscountOffer>(
      ENDPOINT.claim,
      "POST",
      { device_key: deviceKey },
      true,
      { "X-Device-Key": deviceKey }
    );
    if (res.ok && res.data) {
      const offer = { percent: res.data.percent, expires_at: res.data.expires_at };
      setActive(offer);
      return offer;
    }
    if (res.status === 400) {
      // Скидка уже неактуальна/использована — тихо закрываем попап, без ошибки в UI.
      setShowPopup(false);
      setPopupOffer(null);
    }
    return null;
  }, [deviceKey]);

  const dismiss = useCallback(() => {
    setShowPopup(false);
    setPopupOffer(null);
    if (deviceKey) {
      // Не блокируем UI ответом — закрытие попапа мгновенное.
      fetchData(ENDPOINT.dismiss, "POST", { device_key: deviceKey }, true, {
        "X-Device-Key": deviceKey,
      }).catch(() => {});
    }
  }, [deviceKey]);

  // secondsLeft всегда пересчитывается из active.expires_at, а не декрементируется
  // независимым таймером — обновление страницы не расходится с сервером.
  useEffect(() => {
    if (!active?.expires_at) {
      setSecondsLeft(0);
      return;
    }
    const compute = () => {
      const diff = Math.floor((new Date(active.expires_at).getTime() - Date.now()) / 1000);
      setSecondsLeft(Math.max(0, diff));
    };
    compute();
    const id = setInterval(compute, 1000);
    return () => clearInterval(id);
  }, [active?.expires_at]);

  return {
    eligible,
    active,
    showPopup,
    popupOffer,
    deviceKey,
    onExitTrigger,
    claim,
    dismiss,
    secondsLeft,
  };
}
