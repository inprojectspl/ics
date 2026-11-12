# Shared micro-application runtime: the broker and the runner supervisors run
# from this one image. Dependencies come from the lockfile only; application
# packages never trigger an npm install.
FROM node:24.11.1-alpine
WORKDIR /srv
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY src ./src
COPY test ./test
# Socket directories shared between the broker and one runner each. Group
# 10010 is the only group with access; a fresh named volume copies these modes.
RUN addgroup -g 10010 icsrt \
 && adduser -D -H -u 10001 -G icsrt runner \
 && adduser -D -H -u 10002 -G icsrt broker \
 && mkdir -p /run/ics-runner /run/ics-runners/1 /run/ics-runners/2 \
 && chown 10001:10010 /run/ics-runner /run/ics-runners/1 /run/ics-runners/2 \
 && chmod 2770 /run/ics-runner /run/ics-runners/1 /run/ics-runners/2
USER 10002:10010
EXPOSE 8080 8081
CMD ["node", "src/broker/main.js"]
