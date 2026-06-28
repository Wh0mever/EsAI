// Generates public/og-cover.png (1200x630) in the EsAI brand:
// dark ink background (#141414) + gold 4-point spark + "EsAI" wordmark +
// Russian tagline. Pure Node (zlib) — no external image deps required, so it
// runs in CI / locally without `npm install`.
//
// Usage: node scripts/generate-og.mjs
import zlib from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const W = 1200;
const H = 630;
const INK = [0x14, 0x14, 0x14];
const GOLD = [0xf5, 0xc5, 0x18];
const WHITE = [0xed, 0xed, 0xed];

// RGB framebuffer
const buf = Buffer.alloc(W * H * 3);
function setPx(x, y, [r, g, b]) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const i = (y * W + x) * 3;
  buf[i] = r; buf[i + 1] = g; buf[i + 2] = b;
}
function fillRect(x0, y0, w, h, c) {
  for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) setPx(x, y, c);
}
// Background
fillRect(0, 0, W, H, INK);

// Subtle gold radial glow (top-left) — cheap approximation with dithered dots
for (let y = 0; y < H; y++) {
  for (let x = 0; x < W; x++) {
    const dx = x / W, dy = y / H;
    const glow = Math.max(0, 1 - Math.hypot(dx, dy) * 1.6);
    if (glow > 0) {
      const i = (y * W + x) * 3;
      buf[i] = Math.min(255, buf[i] + glow * 30);
      buf[i + 1] = Math.min(255, buf[i + 1] + glow * 24);
      buf[i + 2] = Math.min(255, buf[i + 2] + glow * 3);
    }
  }
}

// 4-point gold spark (concave star), drawn around (cx,cy) with radius R.
function drawSpark(cx, cy, R, c) {
  const waist = R * 0.16; // controls concavity
  for (let y = -R; y <= R; y++) {
    for (let x = -R; x <= R; x++) {
      const ax = Math.abs(x), ay = Math.abs(y);
      // star field: point along axes, pinched between -> astroid-like
      const f = Math.pow(ax / R, 0.62) + Math.pow(ay / R, 0.62);
      if (f <= 1 && (ax < waist + (R - ay) || ay < waist + (R - ax))) {
        setPx(cx + x, cy + y, c);
      }
    }
  }
}
drawSpark(150, 150, 70, GOLD);

// ---- Minimal 5x7 bitmap font (subset: Latin + Cyrillic needed for copy) ----
// Each glyph = 7 rows of 5-bit masks (MSB = leftmost pixel).
const F = {
  "E": [0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f],
  "s": [0x00,0x0f,0x10,0x0e,0x01,0x1e,0x00],
  "A": [0x0e,0x11,0x11,0x1f,0x11,0x11,0x11],
  "I": [0x1f,0x04,0x04,0x04,0x04,0x04,0x1f],
  " ": [0,0,0,0,0,0,0],
  "—": [0x00,0x00,0x00,0x1f,0x00,0x00,0x00],
  "-": [0x00,0x00,0x00,0x1f,0x00,0x00,0x00],
  ".": [0,0,0,0,0,0x06,0x06],
  // Cyrillic (uppercase used in tagline rendering)
  "В": [0x1e,0x11,0x11,0x1e,0x11,0x11,0x1e],
  "С": [0x0e,0x11,0x10,0x10,0x10,0x11,0x0e],
  "Е": [0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f],
  "Н": [0x11,0x11,0x11,0x1f,0x11,0x11,0x11],
  "Й": [0x15,0x1f,0x13,0x15,0x19,0x11,0x11],
  "О": [0x0e,0x11,0x11,0x11,0x11,0x11,0x0e],
  "Р": [0x1e,0x11,0x11,0x1e,0x10,0x10,0x10],
  "Т": [0x1f,0x04,0x04,0x04,0x04,0x04,0x04],
  "И": [0x11,0x11,0x13,0x15,0x19,0x11,0x11],
  "М": [0x11,0x1b,0x15,0x15,0x11,0x11,0x11],
  "У": [0x11,0x11,0x11,0x0f,0x01,0x01,0x0e],
  "Б": [0x1f,0x10,0x10,0x1e,0x11,0x11,0x1e],
  "З": [0x0e,0x11,0x01,0x06,0x01,0x11,0x0e],
  "П": [0x1f,0x11,0x11,0x11,0x11,0x11,0x11],
  "Д": [0x06,0x0a,0x0a,0x0a,0x0a,0x1f,0x11],
  "К": [0x11,0x12,0x14,0x18,0x14,0x12,0x11],
};
function drawText(text, x0, y0, scale, c, fallbackGap = 1) {
  let cx = x0;
  for (const ch of text) {
    const g = F[ch] || F[ch.toUpperCase()];
    if (!g) { cx += (5 + fallbackGap) * scale; continue; }
    for (let r = 0; r < 7; r++) {
      for (let col = 0; col < 5; col++) {
        if (g[r] & (1 << (4 - col))) fillRect(cx + col * scale, y0 + r * scale, scale, scale, c);
      }
    }
    cx += (5 + fallbackGap) * scale;
  }
  return cx;
}

// Wordmark: "EsAI" big, gold accent on "AI"
drawText("Es", 300, 250, 14, WHITE);
drawText("AI", 300 + 2 * (5 + 1) * 14, 250, 14, GOLD);

// Gold underline bar
fillRect(300, 410, 600, 8, GOLD);

// Tagline (uppercased for the bitmap font), gold
drawText("ВСЕ НЕЙРОСЕТИ", 300, 450, 6, GOLD);
drawText("В ОДНОМ МЕСТЕ", 300, 510, 6, WHITE);

// ---- PNG encode (truecolor, no filter) ----
function crc32(b) {
  let c = ~0;
  for (let i = 0; i < b.length; i++) {
    c ^= b[i];
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length, 0);
  const t = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([t, data])), 0);
  return Buffer.concat([len, t, data, crc]);
}
const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4);
ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
// raw scanlines with filter byte 0
const raw = Buffer.alloc(H * (1 + W * 3));
for (let y = 0; y < H; y++) {
  raw[y * (1 + W * 3)] = 0;
  buf.copy(raw, y * (1 + W * 3) + 1, y * W * 3, (y + 1) * W * 3);
}
const idat = zlib.deflateSync(raw, { level: 9 });
const png = Buffer.concat([sig, chunk("IHDR", ihdr), chunk("IDAT", idat), chunk("IEND", Buffer.alloc(0))]);

const __dirname = dirname(fileURLToPath(import.meta.url));
const out = resolve(__dirname, "../public/og-cover.png");
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, png);
console.log("Wrote", out, png.length, "bytes");
