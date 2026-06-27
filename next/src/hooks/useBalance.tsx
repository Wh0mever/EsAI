"use client";

import { useCallback, useEffect, useState } from "react";
import Cookies from "js-cookie";
import { fetchData } from "@/tools/fetchData";

/**
 * useBalance — token balance from GET /api/plans/balance/.
 * Only fetched when an access token is present (chat works anonymously).
 * Refreshes on the "balance:refresh" event and exposes setBalance so the chat
 * can update it directly from a chat response ("balance_tokens").
 */
export function useBalance() {
  const [balance, setBalance] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    if (!Cookies.get("access")) {
      setBalance(null);
      return;
    }
    try {
      const res = await fetchData<{ balance_tokens?: number }>("plans/balance/", "GET", null, true);
      if (res?.ok && res.data && typeof res.data.balance_tokens === "number") {
        setBalance(res.data.balance_tokens);
      }
    } catch {
      /* keep previous value */
    }
  }, []);

  useEffect(() => {
    refresh();
    const onRefresh = () => refresh();
    window.addEventListener("balance:refresh", onRefresh);
    return () => window.removeEventListener("balance:refresh", onRefresh);
  }, [refresh]);

  return { balance, setBalance, refresh };
}
