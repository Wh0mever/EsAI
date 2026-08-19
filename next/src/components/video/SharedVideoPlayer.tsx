"use client";

import { useState } from "react";
import { FiCheck, FiDownload, FiLink } from "react-icons/fi";
import VideoPlayer from "./VideoPlayer";

/**
 * Плеер публичной страницы ролика (/v/<код>) — тот же VideoPlayer плюс два
 * действия, которых ждёт человек, пришедший по ссылке из мессенджера:
 * скачать файл и скопировать ссылку, чтобы переслать дальше.
 *
 * Здесь обычная <a download>, а не saveMedia из чата: страницу открывают в
 * настоящем браузере по ссылке, а не в установленном PWA, где download
 * игнорируется.
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
        <a
          href={src}
          download={downloadName}
          className="inline-flex items-center gap-1.5 text-sm text-muted-2 hover:text-foreground transition-colors"
        >
          <FiDownload className="text-[15px]" />
          Скачать
        </a>
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
