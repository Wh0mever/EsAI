import { ImageResponse } from "next/og";
import { SEO_MODELS, getModel } from "@/lib/seo/models";

// Dynamic OG preview for /model/<slug>. Important for link unfurls in
// Telegram / WhatsApp (primary channels in KG). Dark brand background with a
// golden accent, large model name + "EsAI".
// (Без runtime="edge": Next 16 запрещает edge вместе с generateStaticParams;
// ImageResponse прекрасно работает на Node-runtime, а слаги пререндерим статически.)
export const alt = "EsAI — нейросети в одном месте";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Pre-render an OG image per known model slug at build time.
export function generateStaticParams() {
  return SEO_MODELS.map((m) => ({ slug: m.slug }));
}

const BG = "#141414";
const ACCENT = "#F5C518";

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const model = getModel(slug);
  const name = model?.name ?? "Нейросети";
  const vendor = model?.vendor ?? "";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: BG,
          padding: "72px 80px",
          fontFamily: "sans-serif",
        }}
      >
        {/* top: brand + accent rule */}
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              background: ACCENT,
              display: "flex",
            }}
          />
          <div style={{ fontSize: 40, fontWeight: 700, color: "#ffffff", letterSpacing: -1 }}>
            EsAI
          </div>
        </div>

        {/* center: model name */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          {vendor ? (
            <div
              style={{
                fontSize: 34,
                color: ACCENT,
                textTransform: "uppercase",
                letterSpacing: 4,
                marginBottom: 12,
              }}
            >
              {vendor}
            </div>
          ) : null}
          <div
            style={{
              fontSize: 132,
              fontWeight: 800,
              color: "#ffffff",
              lineHeight: 1,
              letterSpacing: -3,
            }}
          >
            {name}
          </div>
          <div style={{ fontSize: 40, color: "#bdbdbd", marginTop: 28 }}>
            онлайн в EsAI — без VPN, оплата в сомах
          </div>
        </div>

        {/* bottom: accent bar */}
        <div style={{ display: "flex", height: 10, width: 220, background: ACCENT, borderRadius: 6 }} />
      </div>
    ),
    { ...size }
  );
}
