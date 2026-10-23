# Node 22 LTS во всех стадиях. Бюллетень Hostinger от 21.10.2026: исправлены
# Node 22 >= 22.23.4 (24 >= 24.22.1). Тег плавающий, поэтому собирать с
# `docker compose build --pull next` — иначе docker возьмёт старый закэшированный
# node:22-alpine; проверка ниже тогда остановит сборку, а не выкатит старый Node.
ARG NODE_IMAGE=node:22-alpine
ARG NODE_MIN=22.23.4

# --- deps ---
FROM ${NODE_IMAGE} AS deps
ARG NODE_MIN
WORKDIR /app

RUN node -e "const want=process.env.NODE_MIN.split('.').map(Number),have=process.versions.node.split('.').map(Number);for(let i=0;i<3;i++){if(have[i]>want[i])break;if(have[i]<want[i]){console.error('Node '+process.versions.node+' is older than '+process.env.NODE_MIN+': rebuild with docker compose build --pull');process.exit(1)}}console.log('node',process.versions.node)"

COPY package.json package-lock.json ./

# Строго по package-lock.json: версии next/react/react-dom задаёт только lock-файл.
RUN npm ci

# --- builder ---
FROM ${NODE_IMAGE} AS builder
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
# Программа Creators: 1 — пункт в меню и подвале, sitemap и индексация /creators
# (ставить вместе с режимом creators_mode=on в админке).
ARG NEXT_PUBLIC_CREATORS_NAV

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY=$NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY \
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN=$NEXT_PUBLIC_FREEDOM_PAY_TOKEN \
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID=$NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID \
    NEXT_PUBLIC_FREEDOM_PAY_TEST=$NEXT_PUBLIC_FREEDOM_PAY_TEST \
    NEXT_PUBLIC_VSTUDIO_NAV=$NEXT_PUBLIC_VSTUDIO_NAV \
    NEXT_PUBLIC_CREATORS_NAV=$NEXT_PUBLIC_CREATORS_NAV

COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY tsconfig.json ./
COPY next.config.ts ./
COPY postcss.config.mjs ./
COPY public ./public
COPY src ./src

# Safety check: установленные next/react/react-dom обязаны совпадать с
# package-lock.json (ловит любую установку мимо lock-файла).
RUN node -e "const lock=require('./package-lock.json').packages;for(const p of ['next','react','react-dom']){const want=(lock['node_modules/'+p]||{}).version,have=require(p+'/package.json').version;if(!want||want!==have){throw new Error(p+' version mismatch: installed '+have+', package-lock '+want)}console.log(p,have)}"

RUN npx next telemetry disable || true
RUN npm run build

# --- runner ---
FROM ${NODE_IMAGE} AS runner
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
