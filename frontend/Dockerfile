# AI Video Studio frontend: multi-stage Next.js standalone build.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked into the rewrite rules at build time; "backend" is the compose service name.
ARG BACKEND_URL=http://backend:8000
# NEXT_PUBLIC_* is inlined at build time — auth on/off is a build decision.
ARG NEXT_PUBLIC_AUTH_ENABLED=true
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_PUBLIC_AUTH_ENABLED=${NEXT_PUBLIC_AUTH_ENABLED} \
    NEXT_TELEMETRY_DISABLED=1
# `npm run build` runs prisma generate first (schema only, no DB connection).
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
