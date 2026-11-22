import "@/assets/style.scss";
import type { Metadata } from "next";
import ChatHome from "@/components/chat/ChatHome";
import { OG_IMAGE_META, SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "@/lib/seo/site";

// Чат по своему адресу. Заголовок — тот же, что был у главной, когда главной
// был чат: поисковые запросы «чат с нейросетями» ведут сюда. С этапа A6 «/» —
// хаб платформы, поэтому og:url тоже свой (иначе наследовался адрес главной).
const TITLE = "Чаты ИИ — ChatGPT, Claude, Gemini и другие в одном окне | EsAI";

export const metadata: Metadata = {
  title: TITLE,
  alternates: { canonical: "/chat" },
  openGraph: {
    images: [OG_IMAGE_META],
    title: TITLE,
    description: SITE_DESCRIPTION,
    url: `${SITE_URL}/chat`,
    siteName: SITE_NAME,
    type: "website",
  },
};

export default function ChatPage() {
  return <ChatHome />;
}
