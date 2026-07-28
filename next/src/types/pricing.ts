// next/src/types/pricing.ts
//
// Общие типы ответа публичного эндпоинта
// GET /api/plans/packages/value/ (core/plans/views.py TokenPackageValueListView,
// core/plans/credit_value.py compute_all_packages_value).
//
// value.<category> = { count, unit_model_name, recommended } — recommended
// проставляется полностью на бэке (см. _mark_recommended), фронт его не
// пересчитывает, только отображает. Категория может отсутствовать у
// конкретного пакета (эталонная модель не настроена для неё).
//
// Поля tokens/bonus_tokens/featured опциональны — их использует
// HomePricingPreview, но не использует WhatsEnoughCalculator; общий тип
// покрывает оба набора использования без потери типобезопасности.

export type ValueCategory = {
  count: number;
  unit_model_name?: string;
  recommended?: boolean;
};

export type PackageValue = {
  text?: ValueCategory;
  image?: ValueCategory;
  video?: ValueCategory;
  document?: ValueCategory;
};

export type PkgWithValue = {
  id: number | string;
  name: string;
  price: number | string;
  currency: string;
  badge?: string;
  sort_order?: number;
  tokens?: number;
  bonus_tokens?: number;
  featured?: boolean;
  value?: PackageValue;
};
