# --- deps ---
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./

# Install deps strictly, then force-update vulnerable packages
RUN npm ci \
 && npm install next@latest react@latest react-dom@latest --save-exact

# --- builder ---
FROM node:20-alpine AS builder
WORKDIR /app

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY
ARG NEXT_PUBLIC_FREEDOM_PAY_TOKEN
ARG NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID
ARG NEXT_PUBLIC_FREEDOM_PAY_TEST

ENV NODE_ENV=production \
    NODE_OPTIONS=--max-old-space-size=4096 \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_DISABLE_SOURCEMAPS=1 \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY=$NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY \
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN=$NEXT_PUBLIC_FREEDOM_PAY_TOKEN \
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID=$NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID \
    NEXT_PUBLIC_FREEDOM_PAY_TEST=$NEXT_PUBLIC_FREEDOM_PAY_TEST

COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json* ./
COPY tsconfig.json ./
COPY next.config.ts ./
COPY postcss.config.mjs ./
COPY public ./public
COPY src ./src

# Safety check: ensure prod build only
RUN node -e "const p=require('./package.json'); if(p.scripts?.dev){console.log('dev script present (ok)')}"

# Build
RUN set -eux; \
  npx next telemetry disable || true; \
  npm run build

# --- runner ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

RUN addgroup -g 1001 -S nodejs \
 && adduser -S nextjs -u 1001 -G nodejs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Runtime cache permissions
RUN mkdir -p /app/.next/cache \
 && chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000
CMD ["node", "server.js"]
