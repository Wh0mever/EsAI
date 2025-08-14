"use client";

import Script from "next/script";
import React from "react";

declare global {
  interface Window {
    FreedomPaySDK?: any;
    FreedomPay?: any;
    freedomPay?: any;
    __fp_script_loaded__?: boolean;
  }
}

export default function FreedomPayLoader() {
  return (
    <Script
      src="https://cdn.freedompay.kg/sdk/js-sdk-1.0.0.js"
      strategy="afterInteractive"
      onLoad={() => {
        window.__fp_script_loaded__ = true;
        const g = window.FreedomPaySDK || window.FreedomPay || window.freedomPay;
        if (g) window.FreedomPaySDK = g; // alias to canonical name
        console.debug("FreedomPay script loaded, global:", !!window.FreedomPaySDK);
      }}
      onError={(e) => {
        console.error("FreedomPay script load error", e);
      }}
    />
  );
}
