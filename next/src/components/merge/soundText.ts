"use client";

import { useTranslation } from "react-i18next";
import { soundParts, type SoundInfo, type SoundPart } from "./audioLogic";
import type { MergeClipSound } from "./mergeTypes";

/**
 * Подписи звука склейки, общие для дока, подтверждения, итога и панели:
 * «голос, музыка, ролики тише», что уже оплачено, как звучат ролики.
 */
export function useSoundText() {
  const { t } = useTranslation("vstudio", { useSuspense: false });

  const part = (p: SoundPart): string => {
    switch (p) {
      case "voice":
        return t("merge.audio.part.voice", { defaultValue: "голос" });
      case "music":
        return t("merge.audio.part.music", { defaultValue: "музыка" });
      case "own":
        return t("merge.audio.part.own", { defaultValue: "свой трек" });
      case "quiet":
        return t("merge.audio.part.quiet", { defaultValue: "ролики тише" });
      case "off":
        return t("merge.audio.part.off", { defaultValue: "ролики без звука" });
    }
  };

  /** «голос, музыка, ролики тише»; звука нет — пусто. */
  const list = (info: SoundInfo): string => soundParts(info).map(part).join(", ");

  /** Что уже оплачено — «Склеить» второй раз за это не спишет. */
  const paid = (which: "voice" | "music" | "both" | null): string | null => {
    if (which === "both") return t("merge.audio.paid.both", { defaultValue: "Голос и музыка уже оплачены — второй раз не спишутся" });
    if (which === "voice") return t("merge.audio.paid.voice", { defaultValue: "Голос уже оплачен — второй раз не спишется" });
    if (which === "music") return t("merge.audio.paid.music", { defaultValue: "Музыка уже оплачена — второй раз не спишется" });
    return null;
  };

  const clip = (c: MergeClipSound): string => {
    if (c === "quiet") return t("merge.audio.clip.quiet", { defaultValue: "Тише" });
    if (c === "off") return t("merge.audio.clip.off", { defaultValue: "Выключить" });
    return t("merge.audio.clip.keep", { defaultValue: "Оставить" });
  };

  return { part, list, paid, clip };
}
