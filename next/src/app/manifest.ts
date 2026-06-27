import type { MetadataRoute } from "next";

// PWA manifest (ТЗ 2.14). Served at /manifest.webmanifest by Next.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "EsAI — Все AI в одном месте",
    short_name: "EsAI",
    description:
      "EsAI — все нейросети в одном чате: ChatGPT, DeepSeek, Claude, Gemini. На русском, кыргызском и английском.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    display_override: ["standalone", "minimal-ui"],
    orientation: "portrait",
    background_color: "#141414",
    theme_color: "#141414",
    lang: "ru",
    dir: "ltr",
    categories: ["productivity", "utilities"],
    icons: [
      // PNG raster icons (broadest installer support)
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      // Scalable fallbacks
      { src: "/esai-icon-any.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/esai-icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
