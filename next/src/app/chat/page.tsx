import "@/assets/style.scss";
import type { Metadata } from "next";
import ChatHome from "@/components/chat/ChatHome";

// Чат по своему адресу. Заголовок и описание — те же, что были у главной,
// когда главной был чат: поисковые запросы «чат с нейросетями» ведут сюда.
export const metadata: Metadata = {
  title: "Чаты ИИ — ChatGPT, Claude, Gemini и другие в одном окне | EsAI",
  alternates: { canonical: "/chat" },
};

export default function ChatPage() {
  return <ChatHome />;
}
