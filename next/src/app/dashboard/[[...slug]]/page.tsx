import { notFound } from "next/navigation";
import ClientDashboard from "./ClientDashboard";
import Footer from "@/components/main/Footer";
import { CHAT_MODES, type ChatMode } from "@/types/chat";

export const dynamicParams = true;

export function generateStaticParams() {
  return CHAT_MODES.map((slug) => ({ slug: [slug] }));
}

type Params = { slug?: string[] };

export default async function Page({ params }: { params: Promise<Params> }) {
  const { slug: parts = [] } = await params;
  if (parts.length === 0 || parts.length > 2) notFound();

  const [slug, chatId] = parts;
  if (!CHAT_MODES.includes(slug as ChatMode)) notFound();

  // SEO-статья убрана отсюда: клиент попросил, чтобы статьи жили ТОЛЬКО в
  // блоге (/blog). Под чатом остаётся один футер.
  return (
    <>
      <ClientDashboard slug={slug as ChatMode} chatId={chatId ?? null} />
      <Footer />
    </>
  );
}
