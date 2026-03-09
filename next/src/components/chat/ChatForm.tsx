"use client";

import { useRef, useEffect, useState, FormEvent, KeyboardEvent } from "react";
import { Button } from "../ui/buttons/Buttons";
import { TiMicrophoneOutline } from "react-icons/ti";
import { useTranslation } from "react-i18next";
import { IoIosSend, IoIosAttach } from "react-icons/io";
import { IoDocumentTextOutline } from "react-icons/io5";
import AiTemplates from "./ChatTemplates";
import { fetchData, BACKEND } from "@/tools/fetchData";
import { Modal } from "@/components/dialog/Dialog";

export type Message = {
  role: "user" | "assistant";
  content: string;
  variant?: "normal" | "error";
  attachments?: any[];
};

export function ChatForm({
  mode,
	input,
	setInput,
	handleSubmit,
	messages,
  setMessages,
  attachments,
  setAttachments,
  musicLanguage,
  setMusicLanguage,
  musicGenre,
  setMusicGenre,
  musicTrackType,
  setMusicTrackType,
}: {
  mode: "text-chat" | "image-chat" | "music-chat";
	input: string;
	setInput: (val: string) => void;
	handleSubmit: (e: FormEvent) => void;
	messages: Message[];
	setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  attachments: any[];
  setAttachments: React.Dispatch<React.SetStateAction<any[]>>;
  musicLanguage: "ru" | "en" | "kg";
  setMusicLanguage: React.Dispatch<React.SetStateAction<"ru" | "en" | "kg">>;
  musicGenre: string;
  setMusicGenre: React.Dispatch<React.SetStateAction<string>>;
  musicTrackType: "instrumental" | "song";
  setMusicTrackType: React.Dispatch<React.SetStateAction<"instrumental" | "song">>;
}) {
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const { t } = useTranslation("common");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [musicLangModalOpen, setMusicLangModalOpen] = useState(false);
  const [musicGenreModalOpen, setMusicGenreModalOpen] = useState(false);

  const musicLanguages: Array<{ code: "ru" | "en" | "kg"; label: string }> = [
    { code: "ru", label: t("chat.music_lang_ru", { defaultValue: "Русский" }) },
    { code: "en", label: t("chat.music_lang_en", { defaultValue: "English" }) },
    { code: "kg", label: t("chat.music_lang_kg", { defaultValue: "Кыргызча" }) },
  ];

  const musicGenres: Array<{ code: string; label: string }> = [
    { code: "pop", label: t("chat.music_genre_pop", { defaultValue: "Pop" }) },
    { code: "rock", label: t("chat.music_genre_rock", { defaultValue: "Rock" }) },
    { code: "hip-hop", label: t("chat.music_genre_hiphop", { defaultValue: "Hip-Hop" }) },
    { code: "electronic", label: t("chat.music_genre_electronic", { defaultValue: "Electronic" }) },
    { code: "jazz", label: t("chat.music_genre_jazz", { defaultValue: "Jazz" }) },
    { code: "classical", label: t("chat.music_genre_classical", { defaultValue: "Classical" }) },
  ];

  const activeLanguageLabel = musicLanguages.find((item) => item.code === musicLanguage)?.label || musicLanguage.toUpperCase();
  const activeGenreLabel = musicGenres.find((item) => item.code === musicGenre)?.label || musicGenre;

	const handleInput = () => {
		const el = textareaRef.current;
		if (el) {
			el.style.height = "auto";
			el.style.height = el.scrollHeight + "px";
		}
	};

	const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
		const hasUploading = Array.isArray(attachments) && attachments.some((a: any) => a?.status === "uploading");
		if (hasUploading) return; // block submit while uploading
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			handleSubmit(e as any);
		}
	};

	useEffect(() => {
		handleInput();
	}, [input]);

  useEffect(() => {
    if (mode === "music-chat") return;
    setMusicLangModalOpen(false);
    setMusicGenreModalOpen(false);
  }, [mode]);

	const onClickAttach = () => fileInputRef.current?.click();

  const onFilesPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    // optimistic local preview entries
    const pending = files.map((f) => ({
      name: f.name,
      type: f.type?.startsWith("image/") ? "image" : "file",
      preview: URL.createObjectURL(f),
      status: "uploading",
    }));
    setAttachments((prev) => [...prev, ...pending]);

    try {
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      const res = await fetchData<{ attachments: any[] }>("ai/attachments/upload/", "POST", fd, true);
      const ok = !!res?.ok;
      const list = (res?.data as any)?.attachments;

      if (!ok || !Array.isArray(list) || list.length === 0) {
        // Mark pending as error if server didn't accept files
        setAttachments((prev) => {
          const out = [...prev];
          for (let i = out.length - pending.length; i < out.length; i++) {
            if (i >= 0) out[i] = { ...out[i], status: "error" };
          }
          return out;
        });
      } else {
        // replace the last N pending entries with server ones
        setAttachments((prev) => {
          const out = [...prev];
          for (let i = out.length - pending.length, j = 0; i < out.length && j < list.length; i++, j++) {
            const serverItem = list[j];
            // revoke preview URL if exists
            try { if (out[i]?.preview && typeof out[i].preview === 'string') URL.revokeObjectURL(out[i].preview); } catch {}
            out[i] = { ...serverItem, status: "ready" };
          }
          return out;
        });
      }
    } catch (err) {
      console.error("Attachments upload failed", err);
      // mark pending as failed
      setAttachments((prev) => {
        const out = [...prev];
        for (let i = out.length - pending.length; i < out.length; i++) {
          if (i >= 0) out[i] = { ...out[i], status: "error" };
        }
        return out;
      });
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

	return (
		<div className="flex flex-col gap-2">
			{/* Attachments preview above input */}
			{Array.isArray(attachments) && attachments.length > 0 && (
				<div className="mb-3">
					<div className="bg-neutral-900/95 border border-white/10 rounded-xl p-3 shadow-lg">
						<div className="flex items-center justify-between mb-2 text-sm text-neutral-300">
							<div>
								{t("chat.attachments")}: {attachments.length}
							</div>
						</div>
						<div className="flex gap-3">
            {attachments.map((a, idx) => {
              const isImg = a?.type === "image";
              const raw = a?.url || a?.preview || "";
              const abs = raw && typeof raw === "string" && raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
              return (
                <div key={idx} className="relative shrink-0">
                  <button
                    className="absolute -top-2 -right-2 z-100 bg-rose-600 text-white rounded-full w-6 h-6 text-xs cursor-pointer"
                    onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                    title="Remove"
                  >
                    ×
                  </button>
                  {isImg ? (
                    <div className="relative">
                      <img src={abs} alt={a?.name || "attachment"} className="w-24 h-24 object-cover rounded-md" />
                      {a?.status === "uploading" && (
                        <div className="absolute inset-0 bg-black/40 grid place-items-center text-xs text-white rounded-md">{t("status.loading")}</div>
                      )}
                      {a?.status === "error" && (
                        <div className="absolute inset-0 bg-rose-600/40 grid place-items-center text-xs text-white rounded-md">{t("chat.attachment_upload_error")}</div>
                      )}
                    </div>
                  ) : (
                    <a href={abs || undefined} target={abs ? "_blank" : undefined} rel={abs ? "noreferrer" : undefined} className="w-28 h-24 bg-neutral-800 rounded-md grid place-items-center text-xs text-neutral-100 p-2 text-center hover:bg-neutral-700/80">
                      <div className="flex flex-col items-center gap-1">
                        <IoDocumentTextOutline className="text-xl opacity-80" />
                        <span className="truncate max-w-[6rem]">{a?.name || "file"}</span>
                        {a?.status === "uploading" && <span className="text-[10px] opacity-80">{t("status.loading")}</span>}
                        {a?.status === "error" && <span className="text-[10px] text-rose-300">{t("chat.attachment_upload_error")}</span>}
                      </div>
                    </a>
                  )}
                </div>
              );
            })}
						</div>
					</div>
				</div>
			)}
				<form
					onSubmit={handleSubmit}
					className="bg-neutral-900 chat-form sticky bottom-0 left-0 right-0 z-10 w-full border border-neutral-800 px-3 py-2 sm:px-4 sm:py-3 rounded-xl sm:rounded-3xl"
				>
        {mode === "music-chat" && (
          <div className="mb-2 flex items-center gap-2">
              <Button
                type="button"
                className="text-xs sm:text-sm text-gray-100 bg-neutral-800 hover:bg-neutral-700 px-3 py-2 rounded-lg cursor-pointer"
                onClick={() => setMusicGenreModalOpen(true)}
              >
                {t("chat.music_genre", { defaultValue: "Жанр" })}: {activeGenreLabel}
              </Button>

              <Button
                type="button"
                className="text-xs sm:text-sm text-gray-100 bg-neutral-800 hover:bg-neutral-700 px-3 py-2 rounded-lg cursor-pointer"
                onClick={() => setMusicLangModalOpen(true)}
              >
                {t("chat.music_language", { defaultValue: "Язык песни" })}: {activeLanguageLabel}
              </Button>

              <div
                className="ml-auto inline-flex items-center rounded-xl border border-white/15 bg-neutral-800 p-1"
                role="radiogroup"
                aria-label={t("chat.music_track_type", { defaultValue: "Тип трека" })}
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={musicTrackType === "instrumental"}
                  onClick={() => setMusicTrackType("instrumental")}
                  className={[
                    "px-3 py-1.5 text-xs sm:text-sm rounded-lg transition cursor-pointer",
                    musicTrackType === "instrumental"
                      ? "bg-white text-neutral-900 font-medium shadow-sm"
                      : "text-neutral-300 hover:text-white",
                  ].join(" ")}
                >
                  {t("chat.music_type_instrumental", { defaultValue: "Инструментал" })}
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={musicTrackType === "song"}
                  onClick={() => setMusicTrackType("song")}
                  className={[
                    "px-3 py-1.5 text-xs sm:text-sm rounded-lg transition cursor-pointer",
                    musicTrackType === "song"
                      ? "bg-white text-neutral-900 font-medium shadow-sm"
                      : "text-neutral-300 hover:text-white",
                  ].join(" ")}
                >
                  {t("chat.music_type_song", { defaultValue: "Песня" })}
                </button>
              </div>
          </div>
        )}
				<div className="w-full">
					<textarea
						ref={textareaRef}
						onInput={handleInput}
						onKeyDown={handleKeyDown}
						value={input}
						onChange={(e) => setInput(e.target.value)}
						className="w-full chat-textarea resize-none overflow-hidden"
						rows={1}
						placeholder={t("chat.ask_something")}
					/>
				</div>
					<div className="flex justify-between items-center">
						<div className="flex gap-1 mt-2 sm:mt-3">
						{/* attachments */}
						<Button
							type="button"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.attachments")}
							onClick={onClickAttach}
						>
							<IoIosAttach />
						</Button>
						<input
							ref={fileInputRef}
							type="file"
							multiple
							className="hidden"
							onChange={onFilesPicked}
						/>
						<AiTemplates />
					</div>
							<div className="flex gap-1 mt-2 sm:mt-3">
						<Button
							type="button"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.voice_enter")}
						>
							<TiMicrophoneOutline />
						</Button>
					<Button
						type="submit"
						className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full disabled:opacity-50 disabled:cursor-not-allowed"
						disabled={Array.isArray(attachments) && attachments.some((a: any) => a?.status === "uploading")}
						description={t("chat.send")}
					>
						<IoIosSend />
					</Button>
					</div>
				</div>
			</form>

      <Modal
        title={t("chat.music_genre", { defaultValue: "Жанр" })}
        open={musicGenreModalOpen}
        onClose={() => setMusicGenreModalOpen(false)}
        size="sm"
      >
        <div className="flex flex-col gap-2">
          {musicGenres.map((genre) => (
            <button
              key={genre.code}
              type="button"
              onClick={() => {
                setMusicGenre(genre.code);
                setMusicGenreModalOpen(false);
              }}
              className={[
                "w-full text-left px-3 py-2 rounded-md text-sm transition",
                musicGenre === genre.code ? "bg-white/20 text-white" : "hover:bg-white/10 text-neutral-200",
              ].join(" ")}
            >
              {genre.label}
            </button>
          ))}
        </div>
      </Modal>

      <Modal
        title={t("chat.music_language", { defaultValue: "Язык песни" })}
        open={musicLangModalOpen}
        onClose={() => setMusicLangModalOpen(false)}
        size="sm"
      >
        <div className="flex flex-col gap-2">
          {musicLanguages.map((language) => (
            <button
              key={language.code}
              type="button"
              onClick={() => {
                setMusicLanguage(language.code);
                setMusicLangModalOpen(false);
              }}
              className={[
                "w-full text-left px-3 py-2 rounded-md text-sm transition",
                musicLanguage === language.code ? "bg-white/20 text-white" : "hover:bg-white/10 text-neutral-200",
              ].join(" ")}
            >
              {language.label}
            </button>
          ))}
        </div>
      </Modal>
		</div>
	);
}
