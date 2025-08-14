'use client';
import Script from 'next/script';

export default function FreedomPayLoader() {
  return (
    <Script
      src="https://cdn.freedompay.kg/sdk/js-sdk-1.0.0.js"
      strategy="beforeInteractive"
      onLoad={() => { (window as any).__fp_loaded__ = true; }}
    />
  );
}
