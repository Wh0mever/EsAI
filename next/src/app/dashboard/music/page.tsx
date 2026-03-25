"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import { useEffect, useState } from "react";
import Sidebar from "@/components/chat/ChatAside";
import { fetchData } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import { useTranslation } from "react-i18next";
import { MusicTrackCard, type MusicItem } from "@/components/music/MusicTrackCard";

type Chat = { id: string; uid?: string; title: string; chat_mode: string };

function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (Array.isArray(obj.results)) return obj.results as T[];
    if (Array.isArray(obj.data)) return obj.data as T[];
  }
  return [];
}

function sortNewestFirst<T extends { id: number; created_at: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const timeDiff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    if (timeDiff !== 0) return timeDiff;
    return b.id - a.id;
  });
}

export default function MusicLibraryPage() {
  const { t } = useTranslation("common");
  const [chatsList, setChatsList] = useState<Chat[]>([]);
  const [tracks, setTracks] = useState<MusicItem[]>([]);
  const [canDownloadMp4, setCanDownloadMp4] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const profile = await fetchData("users/profile/", "GET", null, true);
        const enabled = Boolean((profile?.data as any)?.subscription?.plan?.mp4_enabled);
        if (mounted) setCanDownloadMp4(enabled);
      } catch {
        if (mounted) setCanDownloadMp4(false);
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
        const s = await fetchData("ai/sessions/", "GET", null, true);
        if (mounted) {
          const list = asArray<Chat>(s?.data).filter((x) => x?.chat_mode === "music-chat");
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
        if (mounted) setTracks(sortNewestFirst(asArray<MusicItem>(r?.data)));
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
                return (
                  <MusicTrackCard
                    key={track.id}
                    track={track}
                    canDownloadMp4={canDownloadMp4}
                    onTrackChange={(updated) => {
                      setTracks((prev) => prev.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)));
                    }}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
