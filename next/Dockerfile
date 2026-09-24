# --- deps ---
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./

# Install deps from lock, then force exact Next.js version
RUN npm ci \
 && npm install next@16.0.8 react@19.0.0 react-dom@19.0.0 --save-exact \
 && npm dedupe

# --- builder ---
FROM node:20-alpine AS builder
WORKDIR /app

ENV NODE_ENV=production \
    NODE_OPTIONS=--max-old-space-size=4096 \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_DISABLE_SOURCEMAPS=1

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY
ARG NEXT_PUBLIC_FREEDOM_PAY_TOKEN
ARG NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID
ARG NEXT_PUBLIC_FREEDOM_PAY_TEST
# Видеостудия: 1 — пункт меню, sitemap и индексация /video-studio (ставить
# вместе с VSTUDIO_MODE=on на бэкенде). NEXT_PUBLIC_VSTUDIO_FIXTURES сюда не добавлять.
ARG NEXT_PUBLIC_VSTUDIO_NAV

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY=$NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY \
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN=$NEXT_PUBLIC_FREEDOM_PAY_TOKEN \
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID=$NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID \
    NEXT_PUBLIC_FREEDOM_PAY_TEST=$NEXT_PUBLIC_FREEDOM_PAY_TEST \
    NEXT_PUBLIC_VSTUDIO_NAV=$NEXT_PUBLIC_VSTUDIO_NAV

COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json* ./
COPY tsconfig.json ./
COPY next.config.ts ./
COPY postcss.config.mjs ./
COPY public ./public
COPY src ./src

# Safety check: fail build if wrong Next.js version
RUN node -e "const v=require('next/package.json').version; if(v!=='16.0.8'){throw new Error('Next.js version mismatch: '+v)}"

RUN npx next telemetry disable || true
RUN npm run build

# --- runner ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# Без этого Next standalone слушает на хостнейме контейнера, и docker-healthcheck
# по localhost:3000 падает (контейнер виснет в unhealthy, хотя nginx ходит по DNS).
# Биндим на все интерфейсы — отвечают и nginx, и healthcheck.
ENV HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs \
 && adduser -S nextjs -u 1001 -G nodejs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

RUN mkdir -p /app/.next/cache \
 && chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000
CMD ["node", "server.js"]
