// ics-microapp-runtime broker: one shared gateway and data broker for every
// micro-application, plus a private admin port for ICS.
import crypto from "node:crypto";
import http from "node:http";
import { adminHandler } from "./admin.js";
import { AppRegistry } from "./apps.js";
import { PoolRegistry } from "./db.js";
import { Gateway } from "./gateway.js";
import { IcsClient } from "./ics.js";
import { RateLimiter } from "./ratelimit.js";
import { RunnerPool } from "./runners.js";

function required(name) {
  const value = process.env[name];
  if (!value) {
    process.stderr.write(`missing ${name}\n`);
    process.exit(2);
  }
  return value;
}

const config = {
  icsInternalUrl: required("ICS_INTERNAL_URL"),
  icsPublicBaseUrl: required("ICS_PUBLIC_BASE_URL"),
  serviceToken: required("ICS_MICROAPPS_SERVICE_TOKEN"),
  sessionSecret: required("ICS_MICROAPPS_SESSION_SECRET"),
  hostSuffix: required("ICS_MICROAPPS_APP_HOST_SUFFIX").toLowerCase(),
  // Public aliases of app origins (e.g. a tunnel): "public.host=<asset hex>,...".
  // Requests on an alias sign in through ICS_MICROAPPS_PUBLIC_ICS_URL.
  aliases: new Map(
    (process.env.ICS_MICROAPPS_PUBLIC_ALIASES ?? "")
      .split(",")
      .map((x) => x.trim().toLowerCase().split("="))
      .filter(([h, hex]) => h && /^[0-9a-f]{32}$/.test(hex ?? "")),
  ),
  publicIcsUrl: process.env.ICS_MICROAPPS_PUBLIC_ICS_URL || null,
  runnerSockets: required("ICS_MICROAPPS_RUNNER_SOCKETS").split(",").filter(Boolean),
  maxConnections: Number(process.env.ICS_MICROAPPS_DB_MAX_CONNECTIONS ?? 24),
  idleSeconds: Number(process.env.ICS_MICROAPPS_IDLE_SECONDS ?? 600),
  // Shared token buckets: refill per second, burst twice that; without Redis
  // each process counts alone.
  redisUrl: process.env.ICS_MICROAPPS_REDIS_URL || null,
  rateLimits: {
    userPerSecond: Number(process.env.ICS_MICROAPPS_RATE_USER_PER_SECOND ?? 20),
    linkPerSecond: Number(process.env.ICS_MICROAPPS_RATE_LINK_PER_SECOND ?? 100),
  },
  port: Number(process.env.PORT ?? 8080),
  adminPort: Number(process.env.ADMIN_PORT ?? 8081),
};

const incarnation = crypto.randomUUID();
const ics = new IcsClient({ baseUrl: config.icsInternalUrl, serviceToken: config.serviceToken });
const pools = new PoolRegistry({ maxConnections: config.maxConnections });
const runners = new RunnerPool({ sockets: config.runnerSockets });
const apps = new AppRegistry({ ics, pools, runners, idleSeconds: config.idleSeconds });
const limiter = new RateLimiter({ redisUrl: config.redisUrl });
const gateway = new Gateway({ config, ics, apps, pools, runners, limiter });

const server = http.createServer({ requestTimeout: 15000, headersTimeout: 10000 }, (req, res) => {
  gateway.handle(req, res).catch(() => {
    if (!res.headersSent) res.writeHead(500);
    res.end();
  });
});
server.listen(config.port, "0.0.0.0");
const admin = http.createServer(adminHandler({ config, apps, runners, gateway, incarnation }));
admin.listen(config.adminPort, "0.0.0.0");

setInterval(() => apps.sweepIdle().catch(() => {}), 15000).unref();
setInterval(async () => {
  const logs = apps.drainLogs();
  try {
    await ics.report({ incarnation, sampled_at: new Date().toISOString(), apps: apps.snapshot(), slots: runners.snapshot(), logs });
  } catch {
    // ICS down: keep the logs for the next report instead of dropping them
    apps.logs.unshift(...logs.slice(-200));
  }
}, 10000).unref();

process.stderr.write(`${JSON.stringify({ event: "broker_started", incarnation, port: config.port, adminPort: config.adminPort, slots: config.runnerSockets.length })}\n`);
for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => {
    server.close();
    admin.close();
    limiter.close();
    setTimeout(() => process.exit(0), 2000).unref();
  });
}
