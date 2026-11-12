// Token-bucket request budgets shared by every broker process through Redis:
// a bucket holds up to `burst` requests and refills `perSecond` a second.
// One atomic script checks every bucket of a request and spends from them
// only when all have room. Without Redis (not configured, or down) each
// process keeps its own bounded buckets: a weaker limit, never no limit.
import { createClient } from "redis";

const PREFIX = "microapp:rl:";
const LOCAL_MAX_KEYS = 10000;

// KEYS: buckets; ARGV: now_ms, then burst and perSecond for each key.
const SCRIPT = `
local now = tonumber(ARGV[1])
local state = {}
for i, key in ipairs(KEYS) do
  local burst = tonumber(ARGV[i * 2])
  local rate = tonumber(ARGV[i * 2 + 1])
  local b = redis.call('HMGET', key, 't', 'at')
  local tokens = tonumber(b[1]) or burst
  local at = tonumber(b[2]) or now
  tokens = math.min(burst, tokens + math.max(0, now - at) / 1000 * rate)
  if tokens < 1 then return 0 end
  state[i] = {tokens, math.ceil(burst / rate * 1000) + 1000}
end
for i, key in ipairs(KEYS) do
  redis.call('HSET', key, 't', state[i][1] - 1, 'at', now)
  redis.call('PEXPIRE', key, state[i][2])
end
return 1`;

export class RateLimiter {
  constructor({ redisUrl = null } = {}) {
    this.local = new Map();
    this.redis = null;
    if (redisUrl) {
      this.redis = createClient({ url: redisUrl, disableOfflineQueue: true, socket: { connectTimeout: 1000, reconnectStrategy: (n) => Math.min(n * 200, 2000) } });
      this.redis.on("error", () => {});
      this.redis.connect().catch(() => {});
    }
  }

  // True when every bucket ({key, burst, perSecond}) had room; spends one
  // token from each only then.
  async take(buckets) {
    const now = Date.now();
    if (this.redis?.isReady) {
      try {
        const args = [String(now), ...buckets.flatMap((b) => [String(b.burst), String(b.perSecond)])];
        return (await this.redis.eval(SCRIPT, { keys: buckets.map((b) => PREFIX + b.key), arguments: args })) === 1;
      } catch {
        // fall through to the local buckets
      }
    }
    return this.#takeLocal(buckets, now);
  }

  #takeLocal(buckets, now) {
    const states = buckets.map(({ key, burst, perSecond }) => {
      const b = this.local.get(key) ?? { tokens: burst, at: now };
      return { key, b: { tokens: Math.min(burst, b.tokens + (Math.max(0, now - b.at) / 1000) * perSecond), at: now } };
    });
    const ok = states.every(({ b }) => b.tokens >= 1);
    for (const { key, b } of states) {
      if (ok) b.tokens -= 1;
      // Re-insert so the Map's order is least recently used first; only the
      // oldest buckets are dropped, never the whole table.
      this.local.delete(key);
      this.local.set(key, b);
    }
    while (this.local.size > LOCAL_MAX_KEYS) this.local.delete(this.local.keys().next().value);
    return ok;
  }

  close() {
    return this.redis?.isOpen ? this.redis.quit().catch(() => {}) : undefined;
  }
}
