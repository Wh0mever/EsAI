// next.config.ts
import path from 'path';
import type { NextConfig } from 'next';

const config: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  webpack(cfg) {
    cfg.resolve.alias['@'] = path.resolve(__dirname, 'src');
    cfg.resolve.extensions = cfg.resolve.extensions || ['.ts','.tsx','.js','.jsx','.mjs','.cjs','.json'];
    return cfg;
  },
};

export default config;
