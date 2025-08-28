# --- deps ---
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# --- builder ---
FROM node:20-alpine AS builder
WORKDIR /app

ARG NEXT_PUBLIC_API_URL
ARG NEXT_CONFIG=next.config.ts
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json* ./
COPY tsconfig.json ./
COPY ${NEXT_CONFIG} ./next.config.ts
COPY postcss.config.mjs ./postcss.config.mjs
COPY public ./public
COPY src ./src

RUN echo "=== TREE /app ===" && ls -la || true \
 && echo "=== CHECK admin components (ls) ===" && ls -la src/components/admin || true \
 && echo "=== CHECK admin components (find) ===" && find src/components/admin -maxdepth 3 -type f | sed -n '1,200p' || true

RUN node -e "const fs=require('fs');const chk=p=>console.log((fs.existsSync(p)?'OK  ':'MISS'),p);['src/components/admin/AppForm/AppForm.tsx','src/components/admin/AppTable/AppTable.tsx','src/components/admin/SideBar/SideBar.tsx','src/components/admin/AppForm/index.tsx','src/components/admin/AppTable/index.tsx','src/components/admin/SideBar/index.tsx'].forEach(chk)"


RUN echo '--- SRC (first 200) ---' && find src -maxdepth 3 -type f | sed -n '1,200p'

RUN npx next build

# --- runner ---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
USER nextjs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
