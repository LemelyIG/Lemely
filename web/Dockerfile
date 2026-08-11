# syntax=docker/dockerfile:1
#
# Web image: builds the SPA and serves it from nginx, reverse-proxying
# /api to the backend service so the browser sees ONE origin (see
# nginx.conf and docker-compose.yml for the CORS reasoning this exists to
# implement — MISSION.md §3 "Definition of done for deployment").

FROM node:22-slim AS builder

WORKDIR /build

# `puppeteer` is a devDependency used only by the local audit runner
# (web/scripts/audit.mjs, run via `npm run audit`) — not by `npm run build`.
# Its postinstall otherwise tries to download a Chrome binary and fails here
# for lack of `unzip` in this base image; skipping it changes nothing about
# the built SPA (Puppeteer is never imported by build-time code).
ENV PUPPETEER_SKIP_DOWNLOAD=true

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -q -O- http://127.0.0.1:80/ >/dev/null || exit 1
