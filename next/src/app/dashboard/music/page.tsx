"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import { useEffect, useState } from "react";
import Sidebar from "@/components/chat/ChatAside";
import { fetchData, BACKEND, API } from "@/tools/fetchData";
import NextLink from "@/components/ui/nextLink/NextLink";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import Cookies from "js-cookie";

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

function sanitizeFilePart(raw?: string): string {
  const v = (raw || "").trim().replace(/[\\/:*?"<>|]+/g, " ");
  const compact = v.replace(/\s+/g, " ").trim();
  return compact || "track";
}

async function downloadMusicFile(
  trackId: number,
  format: "mp3" | "mp4",
  fallbackName: string,
  sourceUrl?: string,
  trackTitle?: string
): Promise<void> {
  const token = Cookies.get("access");
  const endpoint = format === "mp4"
    ? `ai/music/${trackId}/download-mp4/`
    : `ai/music/${trackId}/download/`;
  const params = new URLSearchParams();
  if (sourceUrl) params.set("source_url", sourceUrl);
  if (trackTitle) params.set("title", trackTitle);
  const suffix = params.toString();
  const res = await fetch(`${API}${endpoint}${suffix ? `?${suffix}` : ""}`, {
    method: "GET",
    headers: {
      Accept: "*/*",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    let backendCode = "";
    try {
      const payload = await res.clone().json();
      backendCode = ((payload as any)?.error || "").toString();
    } catch {}
    throw new Error(`download_failed_${res.status}${backendCode ? `_${backendCode}` : ""}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${fallbackName}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function downloadByDirectUrl(url: string, filename: string): void {
  if (!url) throw new Error("download_url_missing");
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
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

function mapTitleErrorToI18nKey(code?: string): string {
  const v = (code || "").trim();
  switch (v) {
    case "music_not_found":
      return "chat.title_error_music_not_found";
    case "music_title_required":
      return "chat.title_error_required";
    case "music_title_too_long":
      return "chat.title_error_too_long";
    case "music_audio_missing":
      return "chat.title_error_audio_missing";
    case "music_audio_path_unavailable":
      return "chat.title_error_audio_path";
    case "music_audio_format_unsupported":
      return "chat.title_error_audio_format";
    case "music_title_embed_failed":
      return "chat.title_error_embed_failed";
    default:
      return "chat.title_error_unknown";
  }
}

export default function MusicLibraryPage() {
  const { t } = useTranslation("common");
  const [chatsList, setChatsList] = useState<Chat[]>([]);
  const [tracks, setTracks] = useState<MusicItem[]>([]);
  const [canDownloadMp4, setCanDownloadMp4] = useState(false);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [coverModalOpen, setCoverModalOpen] = useState(false);
  const [titleModalOpen, setTitleModalOpen] = useState(false);
  const [activeTrack, setActiveTrack] = useState<MusicItem | null>(null);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverError, setCoverError] = useState("");
  const [coverOk, setCoverOk] = useState("");
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);
  const [selectedCoverUrl, setSelectedCoverUrl] = useState<string>("");
  const [draftTitle, setDraftTitle] = useState("");
  const [titleSaving, setTitleSaving] = useState(false);
  const [titleError, setTitleError] = useState("");
  const [titleOk, setTitleOk] = useState("");
  const [loading, setLoading] = useState(true);
  const [downloadingInfo, setDownloadingInfo] = useState<{ id: number; format: "mp3" | "mp4" } | null>(null);

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

  const openTitleModal = (track: MusicItem) => {
    setActiveTrack(track);
    setDraftTitle((track.title || "Track").trim());
    setTitleError("");
    setTitleOk("");
    setTitleModalOpen(true);
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
                const currentTitle = (track.title || "Track").trim() || "Track";
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
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={downloadingInfo?.id === track.id}
                          onClick={async () => {
                            try {
                              setDownloadingInfo({ id: track.id, format: "mp3" });
                              try {
                                await downloadMusicFile(track.id, "mp3", sanitizeFilePart(currentTitle), src, currentTitle);
                              } catch {
                                downloadByDirectUrl(src, `${sanitizeFilePart(currentTitle)}.mp3`);
                              }
                            } catch (e) {
                              console.error("Failed to download mp3", e);
                            } finally {
                              setDownloadingInfo(null);
                            }
                          }}
                          className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {downloadingInfo?.id === track.id && downloadingInfo?.format === "mp3"
                            ? t("chat.downloading", { defaultValue: "Скачивание..." })
                            : `${t("chat.download", { defaultValue: "Скачать" })} MP3`}
                        </button>
                        {canDownloadMp4 && (
                          <button
                            type="button"
                            disabled={downloadingInfo?.id === track.id}
                            onClick={async () => {
                              try {
                                setDownloadingInfo({ id: track.id, format: "mp4" });
                                await downloadMusicFile(track.id, "mp4", sanitizeFilePart(currentTitle), src, currentTitle);
                              } catch (e) {
                                console.error("Failed to download mp4", e);
                                alert(t("chat.mp4_download_not_available", { defaultValue: "MP4 пока недоступен для этого трека" }));
                              } finally {
                                setDownloadingInfo(null);
                              }
                            }}
                            className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {downloadingInfo?.id === track.id && downloadingInfo?.format === "mp4"
                              ? t("chat.mp4_preparing", { defaultValue: "Собираем MP4..." })
                              : `${t("chat.download", { defaultValue: "Скачать" })} MP4`}
                          </button>
                        )}
                      </div>
                    </div>
                    {canDownloadMp4 && downloadingInfo?.id === track.id && downloadingInfo?.format === "mp4" && (
                      <div className="text-xs text-amber-300">
                        {t("chat.mp4_preparing_hint", { defaultValue: "MP4 собирается, сейчас начнется скачивание. Пожалуйста, подождите." })}
                      </div>
                    )}
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
                      <button
                        type="button"
                        onClick={() => openTitleModal(track)}
                        className="px-3 py-2 text-sm rounded-md bg-white/10 hover:bg-white/20 text-white cursor-pointer"
                      >
                        {t("chat.set_title", { defaultValue: "Название трека" })}
                      </button>
                      <div className="text-sm text-neutral-300">
                        {currentTitle}
                      </div>
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

      <Modal
        title={t("chat.set_title", { defaultValue: "Название трека" })}
        open={titleModalOpen}
        onClose={() => {
          setTitleModalOpen(false);
          setActiveTrack(null);
          setDraftTitle("");
          setTitleError("");
          setTitleOk("");
        }}
        size="md"
      >
        <div className="space-y-4">
          <input
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            className="w-full rounded-md bg-neutral-800 border border-white/10 px-3 py-2 text-white"
            placeholder={t("chat.track_title_placeholder", { defaultValue: "Введите название трека" })}
            maxLength={255}
          />
          {!!titleError && <div className="text-xs text-rose-300">{titleError}</div>}
          {!!titleOk && <div className="text-xs text-emerald-300">{titleOk}</div>}
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              className="px-3 py-2 rounded-md bg-white/10 hover:bg-white/20 text-white text-sm cursor-pointer"
              onClick={() => {
                setTitleModalOpen(false);
                setActiveTrack(null);
                setDraftTitle("");
                setTitleError("");
                setTitleOk("");
              }}
              disabled={titleSaving}
            >
              {t("common.cancel", { defaultValue: "Отмена" })}
            </button>
            <button
              type="button"
              className="px-3 py-2 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white text-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={async () => {
                if (!activeTrack?.id || titleSaving) return;
                setTitleSaving(true);
                setTitleError("");
                setTitleOk("");
                try {
                  const res = await fetchData(`ai/music/${activeTrack.id}/title/`, "POST", { title: draftTitle }, true);
                  if (!res?.ok || !res?.data) {
                    const errCode = ((res?.data as any)?.error || (res as any)?.error || "").toString();
                    setTitleError(t(mapTitleErrorToI18nKey(errCode), { defaultValue: t("chat.title_error_unknown", { defaultValue: "Не удалось сохранить название" }) }));
                    return;
                  }
                  const updated = res.data as MusicItem;
                  setTracks((prev) => prev.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)));
                  setTitleOk(t("chat.title_saved", { defaultValue: "Название сохранено" }));
                  setTimeout(() => {
                    setTitleModalOpen(false);
                    setActiveTrack(null);
                    setDraftTitle("");
                    setTitleError("");
                    setTitleOk("");
                  }, 250);
                } finally {
                  setTitleSaving(false);
                }
              }}
              disabled={titleSaving}
            >
              {titleSaving ? t("common.loading", { defaultValue: "Сохранение..." }) : t("common.save", { defaultValue: "Сохранить" })}
            </button>
          </div>
        </div>
      </Modal>
    </main>
  );
}
