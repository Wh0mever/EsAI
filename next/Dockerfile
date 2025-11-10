# --- deps ---
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# --- builder ---
FROM node:20-alpine AS builder
WORKDIR /app

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY
ARG NEXT_PUBLIC_FREEDOM_PAY_TOKEN
ARG FREEDOM_PAY_PUBLIC_KEY
ARG FREEDOM_PAY_TOKEN
ARG NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID
ARG FREEDOM_PAY_MERCHANT_ID
ARG NEXT_PUBLIC_FREEDOM_PAY_TEST
ARG FREEDOM_PAY_TEST
ARG NEXT_CONFIG=next.config.ts
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY=$NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY \
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN=$NEXT_PUBLIC_FREEDOM_PAY_TOKEN \
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID=$NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID \
    NEXT_PUBLIC_FREEDOM_PAY_TEST=$NEXT_PUBLIC_FREEDOM_PAY_TEST \
    FREEDOM_PAY_PUBLIC_KEY=$FREEDOM_PAY_PUBLIC_KEY \
    FREEDOM_PAY_TOKEN=$FREEDOM_PAY_TOKEN \
    FREEDOM_PAY_MERCHANT_ID=$FREEDOM_PAY_MERCHANT_ID \
    FREEDOM_PAY_TEST=$FREEDOM_PAY_TEST
ENV NODE_ENV=production \
    NODE_OPTIONS=--max-old-space-size=4096 \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_DISABLE_SOURCEMAPS=1

COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json* ./
COPY tsconfig.json ./
COPY ${NEXT_CONFIG} ./next.config.ts
COPY postcss.config.mjs ./postcss.config.mjs
COPY public ./public
COPY src ./src
# Note: .env.local may not be present in build context on CI/servers.
# Next.js will read env from process env at build/runtime. If you need
# .env.local, pass it via compose env or mount as a secret. We avoid failing
# the build when the file is absent.
# (Intentionally not copying .env.local to keep build optional.)

RUN echo "=== TREE /app ===" && ls -la || true \
 && echo "=== CHECK admin components (ls) ===" && ls -la src/components/admin || true \
 && echo "=== CHECK admin components (find) ===" && find src/components/admin -maxdepth 3 -type f | sed -n '1,200p' || true

RUN node -e "const fs=require('fs');const chk=p=>console.log((fs.existsSync(p)?'OK  ':'MISS'),p);['src/components/admin/AppForm/AppForm.tsx','src/components/admin/AppTable/AppTable.tsx','src/components/admin/SideBar/SideBar.tsx','src/components/admin/AppForm/index.tsx','src/components/admin/AppTable/index.tsx','src/components/admin/SideBar/index.tsx'].forEach(chk)"


RUN echo '--- SRC (first 200) ---' && find src -maxdepth 3 -type f | sed -n '1,200p'

# Increase memory for Next build and reduce build-time overhead
# Wrap build to dump npm/Next logs on failure for easier diagnosis
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_DISABLE_ESLINT=1 \
    NEXT_PRIVATE_BUILD_WORKER_THREADS=1

RUN set -eux; \
  npx next telemetry disable || true; \
  NODE_OPTIONS="$NODE_OPTIONS" npm run build || { \
    echo '=== NEXT BUILD FAILED — printing npm logs if present ==='; \
    ls -la /root/.npm/_logs || true; \
    tail -n +1 /root/.npm/_logs/* 2>/dev/null || true; \
    exit 1; \
  }

# --- runner ---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

# Runtime keys should be provided via docker run/compose environment if needed

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
USER nextjs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
