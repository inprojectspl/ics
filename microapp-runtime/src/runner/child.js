// Runner child process: executes one handler at a time for exactly one
// (asset, environment, release, policy generation) key. The supervisor kills
// it and forks a new process (new PID) before another key, after a timeout,
// an out-of-memory event or a protocol violation.
import { runHandler, SandboxError } from "./sandbox.js";
import { compileOnly } from "./compile.js";

const pendingRpc = new Map();
let active = null;
let nextCallId = 1;

function send(message) {
  if (process.connected) process.send(message);
}

process.on("message", async (message) => {
  if (message.t === "rpc_result") {
    if (!active || message.reqId !== active) return;
    const waiter = pendingRpc.get(message.callId);
    if (!waiter) return;
    pendingRpc.delete(message.callId);
    if (message.ok) waiter.resolve(message.value);
    else waiter.reject(Object.assign(new Error(message.error?.message ?? "rpc failed"), message.error ?? {}));
    return;
  }
  if (message.t === "compile") {
    try {
      await compileOnly(message.code, message.filename);
      send({ t: "compiled", reqId: message.reqId, ok: true });
    } catch (err) {
      send({ t: "compiled", reqId: message.reqId, ok: false, error: { code: err.code ?? "syntax_error", message: String(err.message).slice(0, 500) } });
    }
    return;
  }
  if (message.t !== "invoke") return;
  if (active) {
    send({ t: "result", reqId: message.reqId, ok: false, error: { code: "runner_busy", message: "slot busy" } });
    return;
  }
  active = message.reqId;
  const reqId = message.reqId;
  try {
    const { value, pendingRpc: unsettled } = await runHandler({
      code: message.code,
      filename: message.filename,
      input: message.input,
      context: message.context,
      limits: message.limits,
      rpc: (method, args) =>
        new Promise((resolve, reject) => {
          const callId = nextCallId++;
          pendingRpc.set(callId, { resolve, reject });
          send({ t: "rpc", reqId, callId, method, args });
        }),
      log: (args) => send({ t: "log", reqId, args }),
    });
    send({ t: "result", reqId, ok: true, value, pendingRpc: unsettled });
  } catch (err) {
    const error =
      err instanceof SandboxError
        ? { code: err.code, message: String(err.message).slice(0, 500), guest: err.guest }
        : { code: "runner_error", message: String(err?.message ?? err).slice(0, 500) };
    send({ t: "result", reqId, ok: false, error });
  } finally {
    pendingRpc.clear();
    active = null;
  }
});

send({ t: "ready", pid: process.pid });
