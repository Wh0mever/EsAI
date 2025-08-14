'use client';

import { useEffect, useState } from 'react';

declare global {
  interface Window { FreedomPaySDK?: any; __fp_loaded__?: boolean; }
}

export function useFreedomPay() {
  const [sdk, setSdk] = useState<any>(null);

  useEffect(() => {
    let raf: number;
    const wait = () => {
      if (window.FreedomPaySDK) {
        setSdk(window.FreedomPaySDK);
        return;
      }
      if (window.__fp_loaded__) {
        // script loaded but global not yet attached: try next tick
      }
      raf = window.requestAnimationFrame(wait);
    };
    wait();
    return () => { if (raf) cancelAnimationFrame(raf); };
  }, []);

  return sdk;
}
