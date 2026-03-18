"use client";

import { useState } from "react";
import Cookies from "js-cookie";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData, API, BACKEND } from "@/tools/fetchData";
import { useTranslation } from "react-i18next";
import NextLink from "@/components/ui/nextLink/NextLink";

export type MusicItem = {
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

type DownloadInfo = { id: number; format: "mp3" | "mp4" } | null;

function asArray<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (Array.isArray(obj.results)) return obj.results as T[];
    if (Array.isArray(obj.data)) return obj.data as T[];
  }
  return [];
}

export function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
}

function normalizeUrlIdentity(raw?: string): string {
  const abs = toAbsUrl(raw);
  if (!abs) return "";
  try {
    const parsed = new URL(abs, BACKEND || undefined);
    return `${parsed.pathname}${parsed.search}`.toLowerCase();
  } catch {
    return abs.toLowerCase();
  }
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

export function resolveMusicTrack(
  tracks: MusicItem[],
  rawUrl?: string,
  trackId?: number | null
): MusicItem | null {
  if (trackId) {
    const byId = tracks.find((track) => track.id === trackId);
    if (byId) return byId;
  }
  const target = normalizeUrlIdentity(rawUrl);
  if (!target) return null;
  return (
    tracks.find((track) => {
      const musicUrl = normalizeUrlIdentity(track.music_url || "");
      const sourceUrl = normalizeUrlIdentity(track.source_url || "");
      return musicUrl === target || sourceUrl === target;
    }) || null
  );
}

export function MusicTrackCard({
  track,
  canDownloadMp4,
  onTrackChange,
  className = "",
  compact = false,
  showSessionHeader = true,
}: {
  track: MusicItem;
  canDownloadMp4: boolean;
  onTrackChange?: (track: MusicItem) => void;
  className?: string;
  compact?: boolean;
  showSessionHeader?: boolean;
}) {
  const { t } = useTranslation("common");
  const [images, setImages] = useState<ImageItem[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [coverModalOpen, setCoverModalOpen] = useState(false);
  const [titleModalOpen, setTitleModalOpen] = useState(false);
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverError, setCoverError] = useState("");
  const [coverOk, setCoverOk] = useState("");
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);
  const [selectedCoverUrl, setSelectedCoverUrl] = useState("");
  const [draftTitle, setDraftTitle] = useState((track.title || "Track").trim() || "Track");
  const [titleSaving, setTitleSaving] = useState(false);
  const [titleError, setTitleError] = useState("");
  const [titleOk, setTitleOk] = useState("");
  const [downloadingInfo, setDownloadingInfo] = useState<DownloadInfo>(null);

  const src = toAbsUrl(track.music_url || track.source_url || "");
  const cover = toAbsUrl(track.cover_url || "");
  const currentTitle = (track.title || "Track").trim() || "Track";
  const mp4Disabled = !canDownloadMp4 || downloadingInfo?.id === track.id;
  const mp4DisabledHint = t("chat.mp4_plan_locked", {
    defaultValue: "На вашем тарифе эта функция не поддерживается",
  });

  const openCoverModal = async () => {
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
    try {
      setCoverSaving(true);
      setCoverError("");
      setCoverOk("");
      const res = await fetchData(`ai/music/${track.id}/cover/`, "POST", payload, true);
      if (!res?.ok || !res?.data) {
        const errCode = ((res?.data as any)?.error || (res as any)?.error || "").toString();
        setCoverError(
          t(mapCoverErrorToI18nKey(errCode), {
            defaultValue: t("chat.cover_error_unknown", { defaultValue: "Не удалось сохранить обложку" }),
          })
        );
        return false;
      }
      const updated = res.data as MusicItem;
      onTrackChange?.(updated);
      setCoverOk(t("chat.cover_saved", { defaultValue: "Обложка сохранена" }));
      return true;
    } catch {
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

  const saveTitle = async () => {
    if (titleSaving) return;
    setTitleSaving(true);
    setTitleError("");
    setTitleOk("");
    try {
      const res = await fetchData(`ai/music/${track.id}/title/`, "POST", { title: draftTitle }, true);
      if (!res?.ok || !res?.data) {
        const errCode = ((res?.data as any)?.error || (res as any)?.error || "").toString();
        setTitleError(
          t(mapTitleErrorToI18nKey(errCode), {
            defaultValue: t("chat.title_error_unknown", { defaultValue: "Не удалось сохранить название" }),
          })
        );
        return;
      }
      const updated = res.data as MusicItem;
      onTrackChange?.(updated);
      setTitleOk(t("chat.title_saved", { defaultValue: "Название сохранено" }));
      window.setTimeout(() => {
        setTitleModalOpen(false);
        setTitleError("");
        setTitleOk("");
      }, 250);
    } finally {
      setTitleSaving(false);
    }
  };

  return (
    <>
      <div className={`bg-neutral-900 border border-neutral-800 rounded-lg p-4 flex flex-col gap-3 ${className}`}>
        {showSessionHeader && (
          <div className="flex items-center justify-between gap-3">
            {track.session_uid || track.session_id ? (
              <NextLink
                href={`/dashboard/music-chat/${track.session_uid || track.session_id}`}
                className="text-white font-medium hover:underline"
              >
                {track.session_title || track.title || "Music Chat"}
              </NextLink>
            ) : (
              <div className="text-white font-medium">{track.session_title || track.title || "Music Chat"}</div>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
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
          <span title={!canDownloadMp4 ? mp4DisabledHint : undefined} className="inline-flex">
            <button
              type="button"
              disabled={mp4Disabled}
              onClick={async () => {
                if (!canDownloadMp4) return;
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
          </span>
        </div>

        {canDownloadMp4 && downloadingInfo?.id === track.id && downloadingInfo?.format === "mp4" && (
          <div className="text-xs text-amber-300">
            {t("chat.mp4_preparing_hint", { defaultValue: "MP4 собирается, сейчас начнется скачивание. Пожалуйста, подождите." })}
          </div>
        )}

        <div className={`flex ${compact ? "flex-col items-start" : "items-center"} gap-3`}>
          <div className="w-16 h-16 rounded-md overflow-hidden border border-white/10 bg-neutral-800 shrink-0">
            {cover ? (
              <img src={cover} alt="cover" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full grid place-items-center text-[10px] text-neutral-400">No cover</div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void openCoverModal()}
              className="px-3 py-2 text-sm rounded-md bg-white/10 hover:bg-white/20 text-white cursor-pointer"
            >
              {t("chat.set_cover", { defaultValue: "Установить обложку" })}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraftTitle(currentTitle);
                setTitleError("");
                setTitleOk("");
                setTitleModalOpen(true);
              }}
              className="px-3 py-2 text-sm rounded-md bg-white/10 hover:bg-white/20 text-white cursor-pointer"
            >
              {t("chat.set_title", { defaultValue: "Название трека" })}
            </button>
            <div className="text-sm text-neutral-300">{currentTitle}</div>
          </div>
        </div>

        {!!track.prompt && <div className="text-sm text-neutral-300 line-clamp-2">{track.prompt}</div>}
        <audio controls preload="none" src={src} className="w-full" />
        <div className="text-xs text-neutral-400 flex items-center justify-between gap-3">
          <span>{track.created_at ? new Date(track.created_at).toLocaleString() : ""}</span>
          <span>{track.model_name}</span>
        </div>
      </div>

      <Modal
        title={t("chat.set_cover", { defaultValue: "Установить обложку" })}
        open={coverModalOpen}
        onClose={() => {
          setCoverModalOpen(false);
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
                const imageSrc = toAbsUrl(img.image_url || "");
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
                    <img src={imageSrc} alt={img.prompt || "image"} className="w-full h-28 object-cover" />
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
              onClick={async () => {
                if (coverSaving) return;
                if (selectedImageId) {
                  const ok = await applyCover({ image_id: selectedImageId });
                  if (ok) {
                    setCoverModalOpen(false);
                    setSelectedImageId(null);
                    setSelectedCoverUrl("");
                  }
                  return;
                }
                if (selectedCoverUrl) {
                  const ok = await applyCover({ cover_url: selectedCoverUrl });
                  if (ok) {
                    setCoverModalOpen(false);
                    setSelectedImageId(null);
                    setSelectedCoverUrl("");
                  }
                }
              }}
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
          setDraftTitle(currentTitle);
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
                setDraftTitle(currentTitle);
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
              onClick={() => void saveTitle()}
              disabled={titleSaving}
            >
              {titleSaving ? t("common.loading", { defaultValue: "Сохранение..." }) : t("common.save", { defaultValue: "Сохранить" })}
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}
