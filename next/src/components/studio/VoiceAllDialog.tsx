"use client";

import { useTranslation } from "react-i18next";
import { useEffect, useMemo, useState } from "react";
import { FiLoader, FiMic } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import type { AudioConfig } from "./SceneAudioDialog";

/**
 * «Озвучить весь мультфильм».
 *
 * Клиент: одна кнопка — ИИ сам распределяет реплики между персонажами и
 * озвучивает все сцены, но итоговую стоимость человек видит ДО запуска.
 * Поэтому здесь показывается готовый план: что скажет каждый герой, каким
 * голосом и сколько это стоит. Любую реплику можно переписать или выключить,
 * цена пересчитывается на месте.
 */

export type PlanLine = {
  scene_id: number;
  order: number;
  title: string;
  character: { id: number; name: string } | null;
  voice_id: string;
  voice_name: string;
  text: string;
  credits: number;
  has_voice: boolean;
};

export type VoicePlan = { lines: PlanLine[]; total_credits: number; balance?: number };

type Voice = { id: string; name: string; gender: string; age: string; description: string };

export default function VoiceAllDialog({
  open,
  plan,
  config,
  projectId,
  onClose,
  onStarted,
  onNeedCredits,
}: {
  open: boolean;
  plan: VoicePlan | null;
  config: AudioConfig | null;
  projectId: number | null;
  onClose: () => void;
  /** Озвучка поставлена в очередь — студия начинает показывать прогресс. */
  onStarted: () => void;
  onNeedCredits: (required: number, balance: number) => void;
}) {
  const { t } = useTranslation("common");
  const [lines, setLines] = useState<PlanLine[]>([]);
  const [off, setOff] = useState<Set<number>>(new Set());
  const [voices, setVoices] = useState<Voice[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!plan) return;
    setLines(plan.lines);
    setOff(new Set());
    setError("");
  }, [plan]);

  useEffect(() => {
    if (!open || voices.length) return;
    void (async () => {
      const res = await fetchData<Voice[]>("cartoon/audio/voices/", "GET", undefined, false);
      if (res.ok && Array.isArray(res.data)) setVoices(res.data);
    })();
  }, [open, voices.length]);

  const prices = config?.prices;
  // Пустая строка не стоит ничего: сцена без реплики остаётся в списке, чтобы
  // её было видно, но платить за неё не за что.
  const priceOf = (text: string) =>
    prices && text.trim()
      ? Math.max(prices.voice_min, Math.ceil((text.trim().length * prices.voice_per_1k) / 1000))
      : 0;

  const active = useMemo(() => lines.filter((l) => !off.has(l.scene_id) && l.text.trim()), [lines, off]);
  const total = useMemo(() => active.reduce((sum, l) => sum + priceOf(l.text), 0), [active, prices]);
  const alreadyVoiced = lines.some((l) => l.has_voice);

  const setLine = (sceneId: number, patch: Partial<PlanLine>) =>
    setLines((prev) => prev.map((l) => (l.scene_id === sceneId ? { ...l, ...patch } : l)));

  /** Один голос на героя: меняя голос в одной сцене, меняем его во всех сценах героя. */
  const setVoiceForCharacter = (characterId: number | null, sceneId: number, voiceId: string) => {
    const voice = voices.find((v) => v.id === voiceId);
    setLines((prev) =>
      prev.map((l) =>
        (characterId && l.character?.id === characterId) || l.scene_id === sceneId
          ? { ...l, voice_id: voiceId, voice_name: voice?.name || "" }
          : l
      )
    );
  };

  const start = async () => {
    if (!projectId || !active.length) return;
    setBusy(true);
    setError("");
    const res = await fetchData<{ count: number; total_credits: number }>(
      `cartoon/projects/${projectId}/voice-all/`,
      "POST",
      {
        lines: active.map((l) => ({
          scene_id: l.scene_id,
          text: l.text.trim(),
          voice_id: l.voice_id,
          voice_name: l.voice_name,
        })),
        replace: true,
      },
      true
    );
    setBusy(false);
    if (res.ok) {
      onStarted();
      onClose();
      return;
    }
    const d = res.data as any;
    if (d?.required) onNeedCredits(Number(d.required), Number(d.balance ?? 0));
    else setError(d?.detail || res.error || t("studio_ui.voiceall_err"));
  };

  // Человек переписал реплики — случайный клик мимо окна не должен их стереть.
  const edited =
    Boolean(plan) &&
    (off.size > 0 || lines.some((l, i) => l.text !== (plan?.lines[i]?.text ?? l.text)));

  const close = () => {
    if (edited && !confirm(t("studio_ui.voiceall_discard"))) return;
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title={t("studio_ui.voiceall_title")} size="lg">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">{t("studio_ui.voiceall_note")}</p>
        {alreadyVoiced && (
          <p className="text-xs text-status-wait">{t("studio_ui.voiceall_replace")}</p>
        )}

        <div className="flex flex-col gap-2">
          {lines.map((l) => {
            const disabled = off.has(l.scene_id);
            return (
              <div
                key={l.scene_id}
                className={`flex flex-col gap-2 rounded-xl border p-2.5 transition-opacity ${
                  disabled ? "border-border opacity-50" : "border-border bg-surface-2/40"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={!disabled}
                      onChange={(e) =>
                        setOff((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.delete(l.scene_id);
                          else next.add(l.scene_id);
                          return next;
                        })
                      }
                      className="h-4 w-4 accent-[var(--accent)]"
                    />
                    <span className="font-semibold text-foreground">{l.order + 1}.</span>
                    <span className="max-w-[12rem] truncate">{l.title}</span>
                  </label>
                  <span className="text-[11px] text-muted-2">{l.character?.name}</span>
                  <select
                    value={l.voice_id}
                    onChange={(e) => setVoiceForCharacter(l.character?.id ?? null, l.scene_id, e.target.value)}
                    className="ml-auto max-w-[12rem] rounded-lg border border-border bg-surface-2 px-2 py-1 text-xs text-foreground outline-none focus:border-accent cursor-pointer"
                  >
                    {voices.length === 0 && <option value={l.voice_id}>{l.voice_name}</option>}
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                  <span className="w-14 shrink-0 text-right text-[11px] text-muted-2">
                    {priceOf(l.text)} {t("studio_ui.credits_short")}
                  </span>
                </div>
                <textarea
                  value={l.text}
                  onChange={(e) => setLine(l.scene_id, { text: e.target.value.slice(0, 200) })}
                  rows={2}
                  disabled={disabled}
                  className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none focus:border-accent disabled:opacity-60"
                />
              </div>
            );
          })}
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
          <div className="text-sm text-foreground">
            {t("studio_ui.voiceall_total", { count: active.length, credits: total })}
            {typeof plan?.balance === "number" && (
              <span className="ml-2 text-xs text-muted-2">
                {t("studio_ui.balance", { count: plan.balance })}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !active.length}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
          >
            {busy ? <FiLoader className="animate-spin" /> : <FiMic />}
            {t("studio_ui.voiceall_btn", { credits: total })}
          </button>
        </div>
      </div>
    </Modal>
  );
}
