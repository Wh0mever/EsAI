"use client";

import QRCode from "react-qr-code";

/**
 * QR-код на белой подложке — всегда, в любой теме.
 *
 * Инвертированный (светлый на тёмном) код читают далеко не все сканеры, а
 * человек в этот момент стоит с телефоном над экраном и должен просто
 * отсканировать адрес, а не выяснять, почему не получается.
 */
type Props = {
  value: string;
  size?: number;
  label: string;
  className?: string;
};

export default function QrCode({ value, size = 176, label, className = "" }: Props) {
  if (!value) return null;
  return (
    <div
      className={`inline-block rounded-2xl bg-white p-3 ${className}`}
      role="img"
      aria-label={label}
    >
      <QRCode
        value={value}
        size={size}
        level="M"
        bgColor="#ffffff"
        fgColor="#141414"
        style={{ height: "auto", maxWidth: "100%", width: size }}
      />
    </div>
  );
}
