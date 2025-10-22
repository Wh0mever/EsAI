// next.config.ts
import path from 'path';
import type { NextConfig } from 'next';

const config: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // Expose runtime values to the browser bundle at build time.
  // We map server .env vars (from project root .env via docker-compose) to NEXT_PUBLIC_* keys.
  env: {
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY: process.env.FREEDOM_PAY_PUBLIC_KEY,
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN: process.env.FREEDOM_PAY_TOKEN,
  },
  webpack(cfg) {
    cfg.resolve.alias['@'] = path.resolve(__dirname, 'src');
    // Route any imports of 'next-i18next' to 'react-i18next' to use single i18n instance
    cfg.resolve.alias['next-i18next'] = 'react-i18next';
    cfg.resolve.extensions = cfg.resolve.extensions || ['.ts','.tsx','.js','.jsx','.mjs','.cjs','.json'];
    return cfg;
  },
};

export default config;
