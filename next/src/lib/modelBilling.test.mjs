// Витрина тарифов должна подписывать «за картинку» только плоский FLUX-биллинг
// (core/ai/model_billing.py), а цену показывать так же, как её спишут.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/modelBilling.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { fluxCreditsPerImage, isFluxImageModel } from "./modelBilling.ts";

test("FLUX распознаётся так же, как на бэкенде", () => {
  assert.equal(isFluxImageModel("black-forest-labs/flux.2-pro"), true);
  assert.equal(isFluxImageModel("Black-Forest-Labs/FLUX.2-klein-4b"), true);
  assert.equal(isFluxImageModel("someone/flux.2-max:free"), true);
});

test("Nano Banana и прочие токенные модели — не FLUX", () => {
  assert.equal(isFluxImageModel("google/gemini-2.5-flash-image"), false);
  assert.equal(isFluxImageModel("google/gemini-3-pro-image-preview"), false);
  assert.equal(isFluxImageModel("openai/gpt-4o"), false);
  assert.equal(isFluxImageModel(""), false);
  assert.equal(isFluxImageModel(undefined), false);
  assert.equal(isFluxImageModel(null), false);
  // «flux.2» после двоеточия — это суффикс варианта, а не имя модели.
  assert.equal(isFluxImageModel("google/gemini-2.5-flash-image:flux.2"), false);
});

test("цена FLUX за картинку = max(1, int(coeff))", () => {
  assert.equal(fluxCreditsPerImage(3.5), 3);
  assert.equal(fluxCreditsPerImage(17), 17);
  assert.equal(fluxCreditsPerImage("4.9"), 4);
  assert.equal(fluxCreditsPerImage(0.4), 1);
  assert.equal(fluxCreditsPerImage(0), 1);
  assert.equal(fluxCreditsPerImage(-2), 1);
  assert.equal(fluxCreditsPerImage(undefined), 1);
  assert.equal(fluxCreditsPerImage(null), 1);
  assert.equal(fluxCreditsPerImage("abc"), 1);
});
