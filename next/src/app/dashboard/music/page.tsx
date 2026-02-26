"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import { useEffect, useState } from "react";
import Sidebar from "@/components/chat/ChatAside";
import { fetchData, BACKEND } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import { useTranslation } from "react-i18next";

type Chat = { id: string; uid?: string; title: string; chat_mode: string };
type MusicItem = {
  id: number;
  music_url: string | null;
  source_url?: string | null;
  created_at: string;
  model_name: string;
  prompt: string;
  title: string;
  session_id: number | null;
  session_uid?: string | null;
  session_title?: string | null;
  instrumental: boolean;
  topmedia_task_id?: string;
};

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
}

export default function MusicLibraryPage() {
  const { t } = useTranslation("common");
  const [chatsList, setChatsList] = useState<Chat[]>([]);
  const [tracks, setTracks] = useState<MusicItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const s = await fetchData("ai/sessions/", "GET", null, true);
        if (mounted) {
          const list = ((s?.data as Chat[]) || []).filter((x) => x?.chat_mode === "music-chat");
          setChatsList(list);
        }
      } catch {
        if (mounted) setChatsList([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const r = await fetchData("ai/music/", "GET", null, true);
        if (mounted) setTracks((r?.data as MusicItem[]) || []);
      } catch {
        if (mounted) setTracks([]);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const hasTracks = tracks.length > 0;

  return (
    <main className="antialiased h-screen relative mx-auto max-h-screen flex bg-neutral-800/75 gap-5">
      <div className="lg:w-3/12 lg:static absolute left-0 top-0 p-2">
        <Sidebar chats={chatsList} />
      </div>

      <div className="flex lg:w-6/12 w-full px-4 py-6">
        <div className="w-full">
          <h2 className="text-xl font-semibold text-white pb-5">{t("chat.music_library")}</h2>
          {loading ? (
            <div className="text-neutral-300">{t("common.loading")}</div>
          ) : !hasTracks ? (
            <div className="w-full h-[70vh] grid place-items-center">
              <div className="text-center space-y-3">
                <h3 className="text-2xl text-white font-semibold">{t("chat.music_library_empty_title", { defaultValue: "В вашей библиотеке музыки пока пусто!" })}</h3>
                <p className="text-neutral-300">{t("chat.music_library_empty_subtitle", { defaultValue: "Создай свой первый трек вместе с Vokalo прямо сейчас" })}</p>
                <NextLink href="/dashboard/music-chat/" className="inline-block mt-2 px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-700 text-white">
                  {t("chat.models_tabs.music")}
                </NextLink>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {tracks.map((track) => {
                const src = toAbsUrl(track.music_url || track.source_url || "");
                return (
                  <div key={track.id} className="bg-neutral-900 border border-neutral-800 rounded-lg p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-3">
                      {track.session_uid || track.session_id ? (
                        <NextLink href={`/dashboard/music-chat/${track.session_uid || track.session_id}`} className="text-white font-medium hover:underline">
                          {track.session_title || track.title || "Music Chat"}
                        </NextLink>
                      ) : (
                        <div className="text-white font-medium">{track.session_title || track.title || "Music Chat"}</div>
                      )}
                      <a href={src} download className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm">
                        {t("chat.download", { defaultValue: "Скачать" })}
                      </a>
                    </div>
                    {!!track.prompt && <div className="text-sm text-neutral-300 line-clamp-2">{track.prompt}</div>}
                    <audio controls preload="none" src={src} className="w-full" />
                    <div className="text-xs text-neutral-400 flex items-center justify-between gap-3">
                      <span>{track.created_at ? new Date(track.created_at).toLocaleString() : ""}</span>
                      <span>{track.model_name}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
