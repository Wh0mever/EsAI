"use client";

import { Suspense } from "react";
import CreatorDashboard from "@/components/creators/dashboard/CreatorDashboard";
import { DashboardSkeleton } from "@/components/creators/dashboard/ui";

/**
 * /creators/dashboard — кабинет креатора (ТЗ п.13).
 *
 * Раздел выбирается параметром ?tab=, а useSearchParams требует границы
 * Suspense — иначе сборка страницы падает. Пока параметры читаются, на экране
 * тот же каркас, что и при загрузке данных.
 */
export default function CreatorDashboardPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <CreatorDashboard />
    </Suspense>
  );
}
