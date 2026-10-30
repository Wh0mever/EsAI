"use client";

import { useState } from "react";
import { FiCheck, FiLink } from "react-icons/fi";
import VideoPlayer from "./VideoPlayer";
import SaveMediaButton, { SAVE_CTA } from "@/components/ui/SaveMediaButton";

/**
 * Плеер публичной страницы ролика (/v/<код>) — тот же VideoPlayer плюс два
 * действия, которых ждёт человек, пришедший по ссылке из мессенджера:
 * скачать файл и скопировать ссылку, чтобы переслать дальше.
 *
 * Скачивание идёт через нативное сохранение, а не через <a download>: на iPhone
 * такая ссылка не скачивает, а уводит на файл и показывает серую заглушку с
 * иконкой MP4. Ссылками делятся в мессенджерах, то есть открывают их как раз с
 * телефона, — здесь это критичнее, чем где-либо ещё.
 */
export default function SharedVideoPlayer({
  src,
  poster,
  downloadName,
}: {
  src: string;
  poster?: string;
  downloadName: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Буфер недоступен (http или отказ в правах) — молча, ссылка и так в адресной строке.
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <VideoPlayer src={src} poster={poster} className="w-full" />
      <div className="flex items-center justify-center gap-5">
        {/* Через нативное сохранение, а не <a download>: на iPhone ссылка не
            скачивает, а открывает файл заглушкой (см. ui/SaveMediaButton). */}
        <SaveMediaButton
          url={src}
          filename={downloadName}
          label="Скачать"
          className={SAVE_CTA}
          warm={false}
        >
          Скачать
        </SaveMediaButton>
        <button
          type="button"
          onClick={() => void copy()}
          className="inline-flex items-center gap-1.5 text-sm text-muted-2 hover:text-foreground transition-colors cursor-pointer"
        >
          {copied ? <FiCheck className="text-[15px] text-emerald-400" /> : <FiLink className="text-[15px]" />}
          {copied ? "Скопировано" : "Скопировать ссылку"}
        </button>
      </div>
    </div>
  );
}
