"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import { useEffect, useState } from "react";
import Sidebar from "@/components/chat/ChatAside";
import { fetchData, BACKEND } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import { useTranslation } from "react-i18next";

type Chat = { id: string; uid?: string; title: string; chat_mode: string };
type UserImage = { id: number; image_url: string | null; created_at: string; size: string; model_name: string; prompt: string; session_id: number | null; uniqid: string };

function sortNewestFirst<T extends { id: number; created_at: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const timeDiff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (timeDiff !== 0) return timeDiff;
    return b.id - a.id;
  });
}

export default function ImagesLibraryPage() {
  const { t } = useTranslation("common");
  const [chatsList, setChatsList] = useState<Chat[]>([]);
  const [images, setImages] = useState<UserImage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const s = await fetchData("ai/sessions/", "GET", null, true);
        if (mounted) setChatsList((s?.data as Chat[]) || []);
      } catch {}
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const r = await fetchData("ai/images/", "GET", null, true);
        if (mounted) setImages(sortNewestFirst((r?.data as UserImage[]) || []));
      } catch {
        if (mounted) setImages([]);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <main className="antialiased h-screen relative mx-auto max-h-screen flex bg-neutral-800/75 gap-5">
      <div className="lg:w-3/12 lg:static absolute left-0 top-0 p-2">
        <Sidebar chats={chatsList} />
      </div>

      <div className="flex lg:w-6/12 w-full px-4 py-6">
        <div className="w-full">
          <h2 className="text-xl font-semibold text-white pb-5">{t("chat.images_library")}</h2>
          {loading ? (
            <div className="text-neutral-300">{t("common.loading")}</div>
          ) : images.length === 0 ? (
            <div className="w-full h-[70vh] grid place-items-center">
              <div className="text-center space-y-3">
                <h3 className="text-2xl text-white font-semibold">{t("chat.images_library_empty_title", { defaultValue: "В вашей библиотеке изображений пока пусто !" })}</h3>
                <p className="text-neutral-300">{t("chat.images_library_empty_subtitle", { defaultValue: "Создай свое первое изображение вместе с vokalo прямо сейчас" })}</p>
                <NextLink href="/dashboard/image-chat/" className="inline-block mt-2 px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
                  DALL·E
                </NextLink>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
              {images.map((img) => (
                <div key={img.id} className="bg-neutral-900 border border-neutral-800 rounded-lg overflow-hidden flex flex-col justify-between">
                  {img.image_url ? (
                    <a href={img.image_url.startsWith("/") ? `${BACKEND}${img.image_url}` : img.image_url} target="_blank" rel="noreferrer">
                      <img src={img.image_url.startsWith("/") ? `${BACKEND}${img.image_url}` : img.image_url} alt={img.prompt?.slice(0, 80) || "generated"} className="w-full object-cover" />
                    </a>
                  ) : (
                    <div className="p-6 text-neutral-500">{t("status.notfound")}</div>
                  )}
                  <div className="p-3 flex items-center justify-between text-sm text-neutral-300">
                    <span>{img.size}</span>
                    {img.image_url && (
                      <a href={img.image_url.startsWith("/") ? `${BACKEND}${img.image_url}` : img.image_url} download className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white">
                        {t("chat.download", { defaultValue: "Скачать" })}
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
