"use client";

import { useTranslation } from "react-i18next";
import { useCallback, useMemo, useState } from "react";
import { FiLoader, FiMic } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { VS_BTN_GOLD, VS_INPUT, vx } from "@/components/vstudio/ui/skin";
import { fetchData } from "@/tools/fetchData";
import type { AudioConfig } from "./SceneAudioDialog";
import type { ApiRefusal } from "./cartoonTypes";
import { linePrice } from "./lineVoice";
import { useVoices } from "./VoicePicker";

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
  /** Реплика, которую написал человек: текст заморожен, озвучивается как есть. */
  line?: boolean;
};

export type VoicePlan = {
  lines: PlanLine[];
  total_credits: number;
  balance?: number;
  /** Сколько сцен уже говорят голосом модели — их озвучивать не надо. */
  spoken_in_video?: number;
  /** Сколько реплик уже озвучено голосом героя: в план они не входят. */
  line_voiced?: number;
  /** Сколько описаний вместо слов героя пропущено: вслух их не читаем. */
  descriptions?: number;
  /** Сколько реплик в неснятых сценах: голос придёт вместе со съёмкой. */
  unshot?: number;
};

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
  const [lines, setLines] = useState<PlanLine[]>(() => plan?.lines ?? []);
  // Уже озвученные сцены снимаем с галочки: их реплики оплачены, и молча
  // заменять их новыми нельзя — но человек может включить их обратно.
  const voicedOff = (p: VoicePlan | null) => new Set((p?.lines ?? []).filter((l) => l.has_voice).map((l) => l.scene_id));
  const [off, setOff] = useState<Set<number>>(() => voicedOff(plan));
  const voices = useVoices(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Пришёл новый план — окно начинается с него. Прежний план помним в состоянии
  // и сверяем при отрисовке, а не в эффекте: так окно не мигает старыми строками.
  const [shownPlan, setShownPlan] = useState(plan);
  if (plan !== shownPlan) {
    setShownPlan(plan);
    if (plan) {
      setLines(plan.lines);
      setOff(voicedOff(plan));
      setError("");
    }
  }

  const prices = config?.prices;
  // Пустая строка не стоит ничего: сцена без реплики остаётся в списке, чтобы
  // её было видно, но платить за неё не за что.
  const priceOf = useCallback((text: string) => linePrice(text, prices), [prices]);

  const active = useMemo(() => lines.filter((l) => !off.has(l.scene_id) && l.text.trim()), [lines, off]);
  const total = useMemo(() => active.reduce((sum, l) => sum + priceOf(l.text), 0), [active, priceOf]);
  const alreadyVoiced = lines.some((l) => l.has_voice);
  const ownLines = lines.some((l) => l.line);

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
    const d = res.data as ApiRefusal;
    if (d?.required) onNeedCredits(Number(d.required), Number(d.balance ?? 0));
    else setError(d?.detail || res.error || t("studio_ui.voiceall_err"));
  };

  // Человек переписал реплики — случайный клик мимо окна не должен их стереть.
  const edited =
    Boolean(plan) &&
    lines.some(
      (l, i) =>
        l.text !== (plan?.lines[i]?.text ?? l.text) ||
        off.has(l.scene_id) !== Boolean(plan?.lines[i]?.has_voice)
    );

  const close = () => {
    if (edited && !confirm(t("studio_ui.voiceall_discard"))) return;
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title={t("studio_ui.voiceall_title")} size="lg">
      <div className="flex flex-col gap-4">
        <p className="text-sm leading-snug text-muted">{t("studio_ui.voiceall_note")}</p>
        {alreadyVoiced && (
          <p className="text-xs leading-snug text-status-wait">{t("studio_ui.voiceall_keep")}</p>
        )}
        {Boolean(plan?.spoken_in_video) && (
          <p className="text-xs leading-snug text-muted-2">
            {t("studio_ui.voiceall_spoken", { count: plan?.spoken_in_video ?? 0 })}
          </p>
        )}
        {ownLines && <p className="text-xs leading-snug text-muted-2">{t("studio_ui.voiceall_own_lines")}</p>}
        {Boolean(plan?.line_voiced) && (
          <p className="text-xs leading-snug text-muted-2">
            {t("studio_ui.voiceall_line_voiced", { n: plan?.line_voiced ?? 0 })}
          </p>
        )}
        {Boolean(plan?.descriptions) && (
          <p className="text-xs leading-snug text-muted-2">
            {t("studio_ui.voiceall_descriptions", { n: plan?.descriptions ?? 0 })}
          </p>
        )}
        {Boolean(plan?.unshot) && (
          <p className="text-xs leading-snug text-muted-2">
            {t("studio_ui.voiceall_unshot", { n: plan?.unshot ?? 0 })}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {lines.map((l) => {
            const disabled = off.has(l.scene_id);
            return (
              <div
                key={l.scene_id}
                className={vx(
                  "flex flex-col gap-2 rounded-xl border border-vs-ink/10 p-2.5 transition-opacity motion-reduce:transition-none",
                  disabled ? "opacity-50" : "bg-vs-ink/[0.03]",
                )}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  {/* Вся строка с номером и названием — зона нажатия галочки: 44 px на телефоне. */}
                  <label className="flex min-h-11 min-w-0 cursor-pointer items-center gap-2 text-xs text-muted md:min-h-8">
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
                      className="size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                    />
                    <span className="font-semibold tabular-nums text-foreground">{l.order + 1}.</span>
                    <span className="max-w-[12rem] truncate">{l.title}</span>
                  </label>
                  <span className="text-[11px] text-muted-2">{l.character?.name}</span>
                  <select
                    value={l.voice_id}
                    onChange={(e) => setVoiceForCharacter(l.character?.id ?? null, l.scene_id, e.target.value)}
                    aria-label={t("studio_ui.audio_voice")}
                    className={vx(
                      VS_INPUT,
                      "ml-auto !min-h-11 !w-auto max-w-[12rem] cursor-pointer !px-2 !text-xs max-sm:!text-base md:!min-h-8",
                    )}
                  >
                    {voices.length === 0 && <option value={l.voice_id}>{l.voice_name}</option>}
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                  <span className="w-14 shrink-0 text-right text-[11px] tabular-nums text-muted-2">
                    {priceOf(l.text)} {t("studio_ui.credits_short")}
                  </span>
                </div>
                <textarea
                  value={l.text}
                  onChange={(e) => setLine(l.scene_id, { text: e.target.value.slice(0, 200) })}
                  rows={2}
                  disabled={disabled}
                  // Слова человека правятся на карточке сцены: сервер всё равно возьмёт их оттуда.
                  readOnly={l.line}
                  placeholder={t("studio_ui.voiceall_line_ph")}
                  className={vx(
                    VS_INPUT,
                    "resize-none py-2 leading-snug max-sm:!text-base disabled:cursor-not-allowed disabled:opacity-60",
                    l.line && "cursor-default text-muted",
                  )}
                />
              </div>
            );
          })}
        </div>

        {error && (
          <p role="alert" className="text-sm leading-snug text-status-fail">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-vs-ink/10 pt-3">
          <div className="text-sm tabular-nums text-foreground">
            {t("studio_ui.voiceall_total", { count: active.length, credits: total })}
            {typeof plan?.balance === "number" && (
              <span className="ml-2 text-xs text-muted-2">
                {t("studio_ui.balance", { count: plan.balance })}
              </span>
            )}
          </div>
          {/* Единственное платное действие окна — золотое. */}
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !active.length}
            aria-busy={busy || undefined}
            className={VS_BTN_GOLD}
          >
            {busy ? <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden /> : <FiMic aria-hidden />}
            {t("studio_ui.voiceall_btn", { credits: total })}
          </button>
        </div>
      </div>
    </Modal>
  );
}
