import { ImageResponse } from "next/og";
import { SEO_FUNCTIONS, getFunction } from "@/lib/seo/functions";

// Dynamic OG preview for /ai/<slug> (use-case landings). Important for link
// unfurls in Telegram / WhatsApp (primary channels in KG). Dark brand
// background with a golden accent, large tool name + "EsAI".
// (Без runtime="edge": Next 16 запрещает edge вместе с generateStaticParams;
// ImageResponse работает на Node-runtime, слаги пререндерим статически.)
export const alt = "EsAI — нейросети в одном месте";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Pre-render an OG image per known function slug at build time.
export function generateStaticParams() {
  return SEO_FUNCTIONS.map((f) => ({ slug: f.slug }));
}

const BG = "#141414";
const ACCENT = "#F5C518";

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const fn = getFunction(slug);
  const name = fn?.name ?? "Нейросети в одном месте";

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
        {/* top: brand + accent mark */}
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

        {/* center: tool / use-case name */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              fontSize: 34,
              color: ACCENT,
              textTransform: "uppercase",
              letterSpacing: 4,
              marginBottom: 16,
            }}
          >
            Нейросети
          </div>
          <div
            style={{
              fontSize: 96,
              fontWeight: 800,
              color: "#ffffff",
              lineHeight: 1.05,
              letterSpacing: -2,
            }}
          >
            {name}
          </div>
          <div style={{ fontSize: 40, color: "#bdbdbd", marginTop: 28 }}>
            в EsAI — без VPN, оплата в сомах
          </div>
        </div>

        {/* bottom: accent bar */}
        <div style={{ display: "flex", height: 10, width: 220, background: ACCENT, borderRadius: 6 }} />
      </div>
    ),
    { ...size }
  );
}
