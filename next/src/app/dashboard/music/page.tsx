"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import { useEffect, useState } from "react";
import Sidebar from "@/components/chat/ChatAside";
import { fetchData, BACKEND } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";

type Chat = { id: string; uid?: string; title: string; chat_mode: string };
type MusicItem = {
  id: number;
  music_url: string | null;
  cover_url?: string | null;
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

type ImageItem = {
  id: number;
  image_url: string | null;
  prompt?: string;
};

function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (Array.isArray(obj.results)) return obj.results as T[];
    if (Array.isArray(obj.data)) return obj.data as T[];
  }
  return [];
}

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
}

function mapCoverErrorToI18nKey(code?: string): string {
  const v = (code || "").trim();
  switch (v) {
    case "music_not_found":
      return "chat.cover_error_music_not_found";
    case "image_not_found":
      return "chat.cover_error_image_not_found";
    case "cover_source_required":
    case "cover_url_required":
      return "chat.cover_error_source_required";
    case "cover_media_path_invalid":
      return "chat.cover_error_media_path_invalid";
    case "cover_open_failed":
    case "image_open_failed":
      return "chat.cover_error_open_failed";
    case "cover_download_failed":
      return "chat.cover_error_download_failed";
    case "cover_empty_payload":
      return "chat.cover_error_empty_payload";
    case "cover_format_unsupported":
      return "chat.cover_error_format_unsupported";
    case "music_audio_missing":
      return "chat.cover_error_audio_missing";
    case "music_audio_path_unavailable":
      return "chat.cover_error_audio_path";
    case "music_audio_format_unsupported":
      return "chat.cover_error_audio_format";
    case "cover_embed_failed":
      return "chat.cover_error_embed_failed";
    default:
      return "chat.cover_error_unknown";
  }
}

export default function MusicLibraryPage() {
  const { t } = useTranslation("common");
  const [chatsList, setChatsList] = useState<Chat[]>([]);
  const [tracks, setTracks] = useState<MusicItem[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [coverModalOpen, setCoverModalOpen] = useState(false);
  const [activeTrack, setActiveTrack] = useState<MusicItem | null>(null);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverError, setCoverError] = useState("");
  const [coverOk, setCoverOk] = useState("");
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);
  const [selectedCoverUrl, setSelectedCoverUrl] = useState<string>("");
  const [loading, setLoading] = useState(true);

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
        if (mounted) setTracks(asArray<MusicItem>(r?.data));
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

  const openCoverModal = async (track: MusicItem) => {
    setActiveTrack(track);
    setSelectedImageId(null);
    setSelectedCoverUrl("");
    setCoverError("");
    setCoverOk("");
    setCoverModalOpen(true);
    setImagesLoading(true);
    try {
      const r = await fetchData("ai/images/", "GET", null, true);
      setImages(asArray<ImageItem>(r?.data));
    } catch {
      setImages([]);
    } finally {
      setImagesLoading(false);
    }
  };

  const applyCover = async (payload: { image_id?: number; cover_url?: string }) => {
    if (!activeTrack?.id) return;
    try {
      setCoverSaving(true);
      setCoverError("");
      setCoverOk("");
      const res = await fetchData(`ai/music/${activeTrack.id}/cover/`, "POST", payload, true);
      if (!res?.ok || !res?.data) {
        const errCode = ((res?.data as any)?.error || (res as any)?.error || "").toString();
        setCoverError(t(mapCoverErrorToI18nKey(errCode), { defaultValue: t("chat.cover_error_unknown", { defaultValue: "Не удалось сохранить обложку" }) }));
        return false;
      }
      const updated = res.data as MusicItem;
      setTracks((prev) => prev.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)));
      setActiveTrack((prev) => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
      setCoverOk(t("chat.cover_saved", { defaultValue: "Обложка сохранена" }));
      return true;
    } catch (e: any) {
      setCoverError(t("chat.cover_error_unknown", { defaultValue: "Не удалось сохранить обложку" }));
      return false;
    } finally {
      setCoverSaving(false);
    }
  };

  const uploadOwnCover = async (file?: File | null) => {
    if (!file || !file.type.startsWith("image/")) return;
    setCoverError("");
    setCoverOk("");
    const fd = new FormData();
    fd.append("files", file);
    const up = await fetchData<{ attachments: any[] }>("ai/attachments/upload/", "POST", fd, true);
    const first = (up?.data as any)?.attachments?.[0];
    const url = first?.url;
    if (typeof url === "string" && url) {
      setSelectedImageId(null);
      setSelectedCoverUrl(url);
    }
  };

  const handleSaveCover = async () => {
    if (coverSaving) return;
    if (selectedImageId) {
      const ok = await applyCover({ image_id: selectedImageId });
      if (ok) {
        setCoverModalOpen(false);
        setActiveTrack(null);
        setSelectedImageId(null);
        setSelectedCoverUrl("");
      }
      return;
    }
    if (selectedCoverUrl) {
      const ok = await applyCover({ cover_url: selectedCoverUrl });
      if (ok) {
        setCoverModalOpen(false);
        setActiveTrack(null);
        setSelectedImageId(null);
        setSelectedCoverUrl("");
      }
    }
  };

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
                const cover = toAbsUrl(track.cover_url || "");
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
                    <div className="flex items-center gap-3">
                      <div className="w-16 h-16 rounded-md overflow-hidden border border-white/10 bg-neutral-800 shrink-0">
                        {cover ? (
                          <img src={cover} alt="cover" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full grid place-items-center text-[10px] text-neutral-400">No cover</div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => openCoverModal(track)}
                        className="px-3 py-2 text-sm rounded-md bg-white/10 hover:bg-white/20 text-white cursor-pointer"
                      >
                        {t("chat.set_cover", { defaultValue: "Установить обложку" })}
                      </button>
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

      <Modal
        title={t("chat.set_cover", { defaultValue: "Установить обложку" })}
        open={coverModalOpen}
        onClose={() => {
          setCoverModalOpen(false);
          setActiveTrack(null);
          setSelectedImageId(null);
          setSelectedCoverUrl("");
        }}
        size="lg"
      >
        <div className="space-y-4">
          <div className="text-sm text-neutral-300">
            {t("chat.cover_hint", { defaultValue: "Выберите изображение из библиотеки или загрузите свою картинку." })}
          </div>

          <label className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer">
            {coverSaving ? t("common.loading") : t("chat.upload_cover", { defaultValue: "Загрузить свою картинку" })}
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void uploadOwnCover(e.target.files?.[0] || null)}
              disabled={coverSaving}
            />
          </label>
          {selectedCoverUrl && (
            <div className="text-xs text-emerald-300">
              {t("chat.cover_selected_upload", { defaultValue: "Загруженная картинка выбрана. Нажмите «Сохранить»." })}
            </div>
          )}
          {!!coverError && <div className="text-xs text-rose-300">{coverError}</div>}
          {!!coverOk && <div className="text-xs text-emerald-300">{coverOk}</div>}

          {imagesLoading ? (
            <div className="text-neutral-300 text-sm">{t("common.loading")}</div>
          ) : images.length === 0 ? (
            <div className="text-neutral-400 text-sm">{t("chat.images_library_empty", { defaultValue: "Пока нет изображений" })}</div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {images.map((img) => {
                const src = toAbsUrl(img.image_url || "");
                return (
                  <button
                    key={img.id}
                    type="button"
                    className={[
                      "rounded-md overflow-hidden border transition cursor-pointer bg-neutral-800",
                      selectedImageId === img.id ? "border-emerald-400" : "border-white/10 hover:border-white/30",
                    ].join(" ")}
                    onClick={() => {
                      setSelectedImageId(img.id);
                      setSelectedCoverUrl("");
                    }}
                    disabled={coverSaving}
                  >
                    <img src={src} alt={img.prompt || "image"} className="w-full h-28 object-cover" />
                  </button>
                );
              })}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              className="px-3 py-2 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer"
              onClick={() => {
                setCoverModalOpen(false);
                setActiveTrack(null);
                setSelectedImageId(null);
                setSelectedCoverUrl("");
              }}
              disabled={coverSaving}
            >
              {t("common.cancel", { defaultValue: "Отмена" })}
            </button>
            <button
              type="button"
              className="px-3 py-2 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => void handleSaveCover()}
              disabled={coverSaving || (!selectedImageId && !selectedCoverUrl)}
            >
              {coverSaving ? t("common.loading", { defaultValue: "Сохранение..." }) : t("common.save", { defaultValue: "Сохранить" })}
            </button>
          </div>
        </div>
      </Modal>
    </main>
  );
}
