/**
 * Воронка первого экрана: что человек нажал до первого запуска (§3.6).
 *
 * Один шаг vstudio_home_pick на все секции; what — откуда нажали, id — что
 * именно (id кадра карусели или «Трендов», сценария, модели, инструмента или
 * uid проекта). Секции зовут trackHomePick сами; карусель, «Тренды» и
 * сценарии считает StudioHome: что делает нажатие на них, решает он.
 */
import { trackVs } from "@/lib/vstudio/api";
import type { VsFunnelMeta } from "@/lib/vstudio/types";

export type HomePickWhat = VsFunnelMeta["vstudio_home_pick"]["what"];

export function trackHomePick(what: HomePickWhat, id: string): void {
  trackVs("vstudio_home_pick", { what, id });
}
