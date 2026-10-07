/**
 * Карточка «Первый и последний кадр»: какая модель нужна, чтобы у панели
 * запроса появились слоты кадров (§2.2 ToolCards).
 *
 * Модель человека не трогаем, если она уже умеет кадры. Иначе берём первую
 * доступную модель видео, которая принимает оба кадра, — порядок задаёт сервер.
 *
 * Модуль без React — его проверяет node-тест tools.test.mjs.
 */
import type { ComposerState, ModelJSON, ModelsResponse } from "@/lib/vstudio/types";
import { findModel, modelsFor } from "../../settings/settingsModel";

type Models = Pick<ModelsResponse, "video" | "image">;

export type FramesPlan =
  /** Текущая модель видео умеет кадры — выбирать нечего. */
  | { kind: "keep" }
  | { kind: "select"; model: ModelJSON }
  /** Кадры умеют только модели платного тарифа: дальше — вход или пэйволл. */
  | { kind: "locked" }
  /** Кадры не умеет ни одна модель (или список ещё не пришёл). */
  | { kind: "none" };

const frames = (m: ModelJSON) => m.caps.frames || [];
const hasBoth = (m: ModelJSON) => frames(m).includes("first_frame") && frames(m).includes("last_frame");

export function framesPlan(models: Models | null, composer: Pick<ComposerState, "kind" | "model">): FramesPlan {
  const current = composer.kind === "video" ? findModel(models, composer.model, "video") : null;
  if (current && frames(current).length > 0) return { kind: "keep" };
  const video = modelsFor(models, "video");
  const open = video.filter((m) => !m.locked);
  // Оба кадра — то, что обещает карточка; модель только с первым кадром — запасной вариант.
  const pick = open.find(hasBoth) ?? open.find((m) => frames(m).length > 0);
  if (pick) return { kind: "select", model: pick };
  return video.some((m) => frames(m).length > 0) ? { kind: "locked" } : { kind: "none" };
}
