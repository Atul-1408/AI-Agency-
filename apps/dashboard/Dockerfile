# ─── Production Multi-Stage Dockerfile for Next.js Dashboard ─────────────
FROM node:20-alpine AS base

# Stage 1: Dependencies
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy package manifests from monorepo root
COPY package.json package-lock.json* ./
COPY apps/dashboard/package.json ./apps/dashboard/

# Install dependencies (ignoring scripts)
RUN npm ci

# Stage 2: Builder
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/dashboard/node_modules ./apps/dashboard/node_modules
COPY . .

# Set production environment for build
ENV NODE_ENV=production
ENV BUILD_STANDALONE=true
ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app/apps/dashboard
RUN npm run build

# Stage 3: Runner
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Public assets & static output
COPY --from=builder /app/apps/dashboard/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/static ./apps/dashboard/.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "apps/dashboard/server.js"]
