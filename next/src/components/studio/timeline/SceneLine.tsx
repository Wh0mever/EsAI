"use client";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader, FiMic, FiPause, FiPlay } from "react-icons/fi";
import { VS_FOCUS, VS_INPUT, VS_LABEL, vx } from "@/components/vstudio/ui/skin";
import { CS_CARD_GOLD } from "../ui/cartoonSkin";
import { dialogueMaxLength } from "../dockLogic";
import { lineVoiceView, type HeroVoices } from "../lineVoice";
import type { StudioScene } from "../SceneTimeline";
import type { VoicePreview } from "../VoicePicker";

/** Подписанная тихая кнопка в строке голоса: 44 px на телефоне. */
const VOICE_LINK = vx(
  "min-h-11 shrink-0 cursor-pointer rounded-lg px-2 text-[12px] font-semibold text-vs-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50 md:min-h-8",
  VS_FOCUS,
);

/**
 * Слова героя на карточке сцены и то, чьим голосом они звучат.
 *
 * Клиент: мультфильм должен смотреться как мультфильм — значит герой должен говорить, и
 * говорить то, что задумал человек. Поэтому поле только про прямую речь: описание модель
 * читала вслух как есть («Он герой играет потом ищет свою маму…»). Голос приходит сам
 * вместе со съёмкой, а всё платное, что здесь можно нажать, показывает цену на кнопке.
 *
 * Поле без управления: пока что-то снимается, лента перечитывается по таймеру, и значение
 * с сервера не должно затирать то, что человек сейчас печатает.
 */
export default function SceneLine({
  scene,
  seconds,
  heroVoices,
  busy,
  preview,
  onDialogue,
  onDub,
  onChangeVoice,
  onRestore,
}: {
  scene: StudioScene;
  /** Длина снимка: под неё считается, сколько слов уместится. */
  seconds: number;
  heroVoices?: HeroVoices;
  busy: boolean;
  preview: VoicePreview;
  onDialogue: (scene: StudioScene, text: string) => void;
  /** Озвучить голосом героя. Нет — голоса на карточке нет (гость). */
  onDub?: (scene: StudioScene) => void;
  onChangeVoice?: (scene: StudioScene) => void;
  onRestore?: (scene: StudioScene) => void;
}) {
  const { t } = useTranslation("common");
  const [used, setUsed] = useState((scene.dialogue || "").length);
  // Нажали «Озвучить» сразу после правки текста: поле теряет фокус на нажатии, карточка
  // занята сохранением, и обычный disabled съел бы этот щелчок. Озвучка сама дождётся слов.
  const pressedFree = useRef(false);
  // Больше 300 знаков сервер не сохранит, а обрезать молча нельзя.
  const max = dialogueMaxLength(seconds);
  const view = onDub ? lineVoiceView(scene, heroVoices) : ({ kind: "none" } as const);

  return (
    <>
      <label className="flex flex-col gap-1.5">
        <span className="flex flex-wrap items-baseline justify-between gap-x-2">
          <span className={VS_LABEL}>{t("studio_ui.dialogue_label")}</span>
          <span className={vx("ml-auto shrink-0 text-[11px] tabular-nums", used > max ? "text-status-wait" : "text-muted-2")}>
            {t("studio_ui.dialogue_fit", { used, max, seconds })}
          </span>
        </span>
        <textarea
          defaultValue={scene.dialogue || ""}
          // Пока идёт озвучка, слова не меняем: она уже идёт по прежним.
          readOnly={busy}
          onChange={(e) => setUsed(e.target.value.length)}
          onBlur={(e) => {
            const next = e.target.value.trim().slice(0, 300);
            if (next !== (scene.dialogue || "")) onDialogue(scene, next);
          }}
          rows={2}
          // Живая речь — около 13 знаков в секунду: длиннее голос пришлось бы
          // ускорять, а потом и выпускать за конец реплики в кадре.
          maxLength={max}
          placeholder={t("studio_ui.dialogue_ph")}
          className={vx(VS_INPUT, "!min-h-16 resize-none py-2 leading-snug !text-[13px] max-sm:!text-base")}
        />
        <span className="text-[11px] leading-snug text-muted-2">
          {t(scene.status === "ready" ? "studio_ui.dialogue_hint_ready" : "studio_ui.dialogue_hint")}
        </span>
      </label>

      {view.kind === "description" && (
        <p className="text-[11px] leading-snug text-muted-2">{t("studio_ui.line_description")}</p>
      )}

      {view.kind === "voice" && (
        <div className="flex flex-col gap-1.5">
          {view.stale && <p className="text-[11px] leading-snug text-status-wait">{t("studio_ui.line_stale")}</p>}

          {(view.voice || view.canChange) && (
            <div className="flex min-w-0 items-center gap-1 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.03] pl-2.5 pr-1">
              {view.voice ? (
                <>
                  <span className="min-w-0 truncate text-[12px] text-muted" title={view.voice.name}>
                    {t("studio_ui.line_voice_label")} <span className="font-semibold text-foreground">{view.voice.name}</span>
                  </span>
                  <VoicePlay id={view.voice.id} name={view.voice.name} preview={preview} />
                </>
              ) : (
                <span className="min-w-0 flex-1 py-1 text-[12px] leading-snug text-muted">
                  {t("studio_ui.line_voice_auto")}
                </span>
              )}
              {view.canChange && onChangeVoice && (
                <button
                  type="button"
                  onClick={() => onChangeVoice(scene)}
                  disabled={busy}
                  className={vx(VOICE_LINK, "ml-auto")}
                >
                  {t(view.voice ? "studio_ui.line_voice_change" : "studio_ui.line_voice_pick")}
                </button>
              )}
            </div>
          )}

          {/* Главное действие карточки готовой сцены без голоса; цена — до нажатия. Озвучка
              идёт несколько секунд: всё это время карточка занята. */}
          {view.dubPrice != null && onDub && (
            <button
              type="button"
              onPointerDown={() => {
                pressedFree.current = !busy;
              }}
              onPointerCancel={() => {
                pressedFree.current = false;
              }}
              // detail 0 — нажатие с клавиатуры: отметка указателя к нему не относится.
              onClick={(e) => {
                if (!busy || (e.detail > 0 && pressedFree.current)) onDub(scene);
                pressedFree.current = false;
              }}
              aria-disabled={busy || undefined}
              aria-busy={busy || undefined}
              // Подпись на телефоне в две строки: text-balance не оставляет «5 кр» одну на второй.
              className={vx(
                CS_CARD_GOLD,
                "!min-h-11 !px-3 !text-[13px] leading-tight text-balance aria-disabled:cursor-wait md:!min-h-9",
              )}
            >
              {busy ? (
                <FiLoader className="shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <FiMic className="shrink-0" aria-hidden />
              )}
              {t("studio_ui.line_voice_btn", { credits: view.dubPrice })}
            </button>
          )}

          {view.canRestore && onRestore && (
            <button
              type="button"
              onClick={() => onRestore(scene)}
              disabled={busy}
              className={vx(VOICE_LINK, "w-full !font-medium !text-muted hover:!text-foreground")}
            >
              {t("studio_ui.line_voice_restore")}
            </button>
          )}
        </div>
      )}
    </>
  );
}

/** ▶ у имени голоса: кружок 32 px, зона нажатия 44 px на телефоне. */
function VoicePlay({ id, name, preview }: { id: string; name: string; preview: VoicePreview }) {
  const { t } = useTranslation("common");
  const on = preview.previewing === id;
  return (
    <button
      type="button"
      onClick={() => preview.play({ id })}
      aria-label={`${t("studio_ui.audio_listen")}: ${name}`}
      aria-pressed={on}
      title={t("studio_ui.audio_listen")}
      // Отрицательные поля: зона нажатия остаётся 44 px, а место в узкой строке — имени голоса.
      className={vx("-mx-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full md:mx-0 md:size-8", VS_FOCUS)}
    >
      <span className="grid size-7 place-items-center rounded-full bg-vs-ink/[0.06] text-foreground transition-colors hover:bg-vs-ink/[0.1]">
        {on ? <FiPause className="size-3" aria-hidden /> : <FiPlay className="size-3" aria-hidden />}
      </span>
    </button>
  );
}
