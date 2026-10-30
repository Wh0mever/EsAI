"use client";

import { useTranslation } from "react-i18next";
import { useState } from "react";
import { FiCheck, FiLoader, FiMic } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { VS_BTN_GOLD, vx } from "@/components/vstudio/ui/skin";
import type { StudioScene } from "./SceneTimeline";
import VoicePicker, { useVoicePreview, useVoices } from "./VoicePicker";
import { pickedVoice, voiceChoiceIsNew, voiceDialogMode, type HeroVoices } from "./lineVoice";

/**
 * Голос героя: «Сменить» на карточке сцены.
 *
 * Голос один на весь мультфильм. У готовой сцены выбор — это новая озвучка за деньги, и
 * цена стоит на кнопке. До съёмки голос просто закрепляется за героем, бесплатно: человек
 * выбирает его заранее и не платит второй раз за переозвучку, если первый не подошёл.
 */
export default function HeroVoiceDialog({
  scene,
  heroVoices,
  onClose,
  onDub,
  onPin,
}: {
  scene: StudioScene | null;
  heroVoices: HeroVoices | undefined;
  onClose: () => void;
  /** Озвучить сцену этим голосом. Вернёт текст отказа; null — готово (или окно покупки). */
  onDub: (scene: StudioScene, voiceId: string) => Promise<string | null>;
  /** Закрепить голос за героем до съёмки. Вернёт текст отказа; null — готово. */
  onPin: (scene: StudioScene, voiceId: string) => Promise<string | null>;
}) {
  const { t } = useTranslation("common");
  const open = Boolean(scene);
  const voices = useVoices(open);
  const preview = useVoicePreview();
  const [voiceId, setVoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Открыли окно у другой сцены — начинаем с её голоса. Сверяем при отрисовке, а не в
  // эффекте: так окно не мигает голосом прошлой сцены.
  const sceneId = scene?.id ?? null;
  const [shownId, setShownId] = useState<number | null>(null);
  if (sceneId !== shownId) {
    setShownId(sceneId);
    setVoiceId(scene ? pickedVoice(scene, heroVoices) : "");
    setError("");
  }

  const mode = scene ? voiceDialogMode(scene) : "pin";
  const price = scene?.line_voice_price ?? null;
  // Цены нет — сервер озвучку не примет: не обещаем то, что откажет.
  const canApply = Boolean(scene) && (mode === "pin" || price != null) && voiceChoiceIsNew(scene as StudioScene, heroVoices, voiceId);

  const close = () => {
    if (busy) return;
    preview.stop();
    onClose();
  };

  const apply = async () => {
    if (!scene || !canApply) return;
    preview.stop();
    setBusy(true);
    setError("");
    const refused = await (mode === "dub" ? onDub : onPin)(scene, voiceId);
    setBusy(false);
    if (refused) setError(refused);
    else onClose();
  };

  return (
    <Modal open={open} onClose={close} title={t("studio_ui.hero_voice_title")}>
      <div className="flex flex-col gap-3">
        <p className="text-xs leading-snug text-muted">
          {scene?.character?.name ? `${scene.character.name}. ` : ""}
          {t(mode === "dub" ? "studio_ui.hero_voice_note_dub" : "studio_ui.hero_voice_note_pin")}
        </p>
        <VoicePicker
          voices={voices}
          value={voiceId}
          onChange={setVoiceId}
          preview={preview}
          className="max-h-[min(18rem,45dvh)]"
        />
        {error && (
          <p role="alert" className="text-sm leading-snug text-status-fail">
            {error}
          </p>
        )}
        {/* Единственное действие окна — золотое; у озвучки цена на самой кнопке. */}
        <button
          type="button"
          onClick={() => void apply()}
          disabled={busy || !canApply}
          aria-busy={busy || undefined}
          className={vx(VS_BTN_GOLD, "w-full")}
        >
          {busy ? (
            <FiLoader className="shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
          ) : mode === "dub" ? (
            <FiMic className="shrink-0" aria-hidden />
          ) : (
            <FiCheck className="shrink-0" aria-hidden />
          )}
          {busy
            ? t("studio_ui.audio_making")
            : mode === "dub"
            ? t("studio_ui.hero_voice_dub", { credits: price ?? 0 })
            : t("studio_ui.hero_voice_pin")}
        </button>
      </div>
    </Modal>
  );
}
