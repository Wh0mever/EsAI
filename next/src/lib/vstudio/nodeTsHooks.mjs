// Node-тесты lib/vstudio: .ts-модули импортируют друг друга без расширения
// ("./types") и через алиас "@/…", как принято в Next. Node так не умеет —
// этот хук резолвит такие пути в .ts-файлы src/. Подключается первой
// строкой теста (import "./nodeTsHooks.mjs"), модули под тестом — через
// динамический import() после него.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/*.test.mjs
import { register } from "node:module";

const SRC = new URL("../../", import.meta.url).href;

const hooks = `
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
const SRC = ${JSON.stringify(SRC)};
const HAS_EXT = /\\.(?:[cm]?[jt]sx?|json)$/;
export async function resolve(specifier, context, next) {
  let spec = specifier;
  if (spec.startsWith("@/")) spec = new URL(spec.slice(2), SRC).href;
  const relative = spec.startsWith("./") || spec.startsWith("../") || spec.startsWith("file:");
  if (relative && !HAS_EXT.test(spec)) {
    const base = new URL(spec, context.parentURL).href;
    for (const ext of [".ts", "/index.ts"]) {
      const candidate = base + ext;
      if (existsSync(fileURLToPath(candidate))) return next(candidate, context);
    }
  }
  return next(spec, context);
}
`;

register("data:text/javascript," + encodeURIComponent(hooks), import.meta.url);
