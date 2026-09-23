import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// eslint-config-next 16 отдаёт flat-конфиг сам: через FlatCompat он падал
// с «Converting circular structure to JSON», и линтер не запускался вовсе.
const eslintConfig = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: [".next/**", "out/**", "build/**", "public/**", "next-env.d.ts"],
  },
];

export default eslintConfig;
