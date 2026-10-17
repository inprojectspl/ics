FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` installs deterministically from the lockfile and resolves
# per-platform optional deps correctly, which native binaries need
# (`lightningcss-linux-x64-musl` on alpine). With `npm install` in npm 10.x
# the musl variant is sometimes skipped and `vite build` fails on require.
RUN npm ci

FROM deps AS dev
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
COPY . .
RUN npm run build

# Prod: one-shot copier. The container runs no HTTP process: it starts on
# deploy, copies the static files into the shared volume `ics_static`
# (mounted at /static) and exits. Ingress-nginx (a separate stack) serves
# the files straight from that volume, mounted :ro.
FROM alpine:3.20 AS prod
COPY --from=build /app/dist /app/dist
CMD ["sh", "-c", "cp -av /app/dist/. /static/ && echo '[frontend] static published to /static' && exit 0"]
