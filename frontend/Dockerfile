# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,id=pai-os-npm,target=/root/.npm,sharing=locked \
    npm ci --prefer-offline --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_FIREBASE_API_KEY
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID
ARG NEXT_PUBLIC_FIREBASE_APP_ID
ARG NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST
ARG NEXT_PUBLIC_ENABLE_DMS=false
# pai-merge: the PAI OS pages are compiled in only when this is "true" (docker-compose.yml sets it).
ARG NEXT_PUBLIC_OS_ENABLED=false
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_FIREBASE_API_KEY=${NEXT_PUBLIC_FIREBASE_API_KEY} \
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN} \
    NEXT_PUBLIC_FIREBASE_PROJECT_ID=${NEXT_PUBLIC_FIREBASE_PROJECT_ID} \
    NEXT_PUBLIC_FIREBASE_APP_ID=${NEXT_PUBLIC_FIREBASE_APP_ID} \
    NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=${NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST} \
    NEXT_PUBLIC_ENABLE_DMS=${NEXT_PUBLIC_ENABLE_DMS} \
    NEXT_PUBLIC_OS_ENABLED=${NEXT_PUBLIC_OS_ENABLED} \
    NEXT_TELEMETRY_DISABLED=1

# webpack remains required because BuildKit/Turbopack has produced stale chunks
# for this repository even when the build reports success.
RUN --mount=type=cache,id=pai-os-next-webpack,target=/app/.next/cache,sharing=locked \
    npx next build --webpack

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
