// One handler invocation inside a fresh QuickJS/WASM instance.
//
// Nothing survives between calls: every invocation instantiates a new WASM
// module, runtime and context. The guest sees plain JSON values and one host
// function (`__ics_call`) that turns SDK calls into broker RPCs; it never gets
// a Node object, a prototype from this process, a socket or a file handle.
import { newQuickJSWASMModuleFromVariant } from "quickjs-emscripten-core";
import RELEASE_SYNC from "@jitl/quickjs-wasmfile-release-sync";
import { GUEST_PRELUDE } from "./prelude.js";

export class SandboxError extends Error {
  constructor(code, message, extra = {}) {
    super(message);
    this.code = code;
    Object.assign(this, extra);
  }
}

const MAX_JSON_BYTES = 1024 * 1024;

function classify(err) {
  // QuickJS reports a hit memory limit as an InternalError "out of memory".
  if (/out of memory/i.test(err.message)) return new SandboxError("memory_limit", "guest heap limit reached");
  return new SandboxError("handler_error", err.message, { guest: err });
}

function guestError(vm, handle) {
  // `dump` copies the value out as plain data; nothing keeps a guest reference.
  const value = vm.dump(handle);
  if (value && typeof value === "object") {
    return {
      name: String(value.name ?? "Error"),
      message: String(value.message ?? "error").slice(0, 500),
      code: typeof value.code === "string" ? value.code.slice(0, 64) : undefined,
      status: Number.isInteger(value.status) ? value.status : undefined,
    };
  }
  return { name: "Error", message: String(value).slice(0, 500) };
}

/**
 * @param {object} job
 * @param {string} job.code            handler module source (ES module, default export)
 * @param {string} job.filename
 * @param {object} job.input           JSON input
 * @param {object} job.context         JSON context (actor, app, request)
 * @param {{memoryBytes:number, cpuMs:number, wallMs:number, stackBytes:number}} job.limits
 * @param {(method:string, args:unknown[]) => Promise<unknown>} job.rpc
 * @returns {Promise<unknown>} the handler's JSON result
 */
export async function runHandler(job) {
  const { limits } = job;
  const QuickJS = await newQuickJSWASMModuleFromVariant(RELEASE_SYNC);
  const runtime = QuickJS.newRuntime();
  runtime.setMemoryLimit(limits.memoryBytes);
  runtime.setMaxStackSize(limits.stackBytes);

  // CPU budget counts only time spent inside the interpreter; waiting for the
  // broker (DB calls) is bounded by the wall deadline the broker enforces.
  let cpuUsed = 0;
  let sliceStart = 0;
  const wallDeadline = Date.now() + limits.wallMs;
  let interrupted = null;
  runtime.setInterruptHandler(() => {
    const now = Date.now();
    if (cpuUsed + (now - sliceStart) > limits.cpuMs) {
      interrupted = "cpu_budget";
      return true;
    }
    if (now > wallDeadline) {
      interrupted = "execution_deadline";
      return true;
    }
    return false;
  });
  const timed = (fn) => {
    sliceStart = Date.now();
    try {
      return fn();
    } finally {
      cpuUsed += Date.now() - sliceStart;
    }
  };

  const vm = runtime.newContext();
  let wake = null;
  const wakeUp = () => {
    const w = wake;
    wake = null;
    if (w) w();
  };
  let pendingRpc = 0;
  // Late RPC answers after the call ended must not touch the dropped context.
  let alive = true;

  try {
    const hostCall = vm.newFunction("__ics_call", (methodHandle, argsHandle) => {
      const method = vm.getString(methodHandle);
      const argsText = vm.getString(argsHandle);
      if (argsText.length > MAX_JSON_BYTES) {
        throw new SandboxError("rpc_too_large", "RPC arguments too large");
      }
      const args = JSON.parse(argsText);
      if (method === "log") {
        // Fire and forget: a log line is not a data operation to wait for.
        job.log?.(args);
        return vm.undefined;
      }
      const deferred = vm.newPromise();
      pendingRpc += 1;
      job
        .rpc(method, Array.isArray(args) ? args : [])
        .then(
          (value) => {
            if (!alive) return;
            const text = JSON.stringify(value ?? null);
            const h = vm.newString(text);
            deferred.resolve(h);
            h.dispose();
          },
          (err) => {
            if (!alive) return;
            const h = vm.newError({ name: "IcsError", message: String(err?.message ?? err) });
            const code = vm.newString(String(err?.code ?? "rpc_failed"));
            vm.setProp(h, "code", code);
            code.dispose();
            if (Number.isInteger(err?.status)) {
              const st = vm.newNumber(err.status);
              vm.setProp(h, "status", st);
              st.dispose();
            }
            deferred.reject(h);
            h.dispose();
          },
        )
        .finally(() => {
          pendingRpc -= 1;
          wakeUp();
        });
      return deferred.handle;
    });
    vm.setProp(vm.global, "__ics_call", hostCall);
    hostCall.dispose();

    const preludeResult = timed(() => vm.evalCode(GUEST_PRELUDE, "ics-sdk.js", { type: "global" }));
    vm.unwrapResult(preludeResult).dispose();

    const moduleResult = timed(() => vm.evalCode(job.code, job.filename, { type: "module" }));
    if (moduleResult.error) {
      const err = guestError(vm, moduleResult.error);
      moduleResult.error.dispose();
      throw new SandboxError(interrupted ?? "handler_load_failed", err.message);
    }
    let exportsHandle = moduleResult.value;
    // Module evaluation returns the namespace, or a promise for it.
    timed(() => runtime.executePendingJobs());
    const ns = vm.getPromiseState(exportsHandle);
    if (ns.type !== "fulfilled") {
      throw new SandboxError("handler_load_failed", "the handler module did not finish loading");
    }
    if (!ns.notAPromise) {
      exportsHandle.dispose();
      exportsHandle = ns.value;
    }
    const fn = vm.getProp(exportsHandle, "default");
    exportsHandle.dispose();
    if (vm.typeof(fn) !== "function") {
      fn.dispose();
      throw new SandboxError("handler_invalid", "the handler module has no default export function");
    }

    const inputHandle = vm.unwrapResult(vm.evalCode(`(${JSON.stringify(JSON.stringify(job.input))})`));
    const ctxJson = vm.unwrapResult(vm.evalCode(`(${JSON.stringify(JSON.stringify(job.context))})`));
    const makeCtx = vm.getProp(vm.global, "__ics_make");
    const parsedArgs = vm.unwrapResult(vm.callFunction(makeCtx, vm.undefined, inputHandle, ctxJson));
    makeCtx.dispose();
    inputHandle.dispose();
    ctxJson.dispose();
    const inputArg = vm.getProp(parsedArgs, "input");
    const ctxArg = vm.getProp(parsedArgs, "ctx");
    parsedArgs.dispose();

    const callResult = timed(() => vm.callFunction(fn, vm.undefined, inputArg, ctxArg));
    fn.dispose();
    inputArg.dispose();
    ctxArg.dispose();
    if (callResult.error) {
      const err = guestError(vm, callResult.error);
      callResult.error.dispose();
      if (interrupted) throw new SandboxError(interrupted, "handler interrupted");
      throw classify(err);
    }
    const promise = callResult.value;

    for (;;) {
      const jobs = timed(() => runtime.executePendingJobs());
      if (jobs.error) {
        const err = guestError(vm, jobs.error);
        jobs.error.dispose();
        if (interrupted) throw new SandboxError(interrupted, "handler interrupted");
        throw classify(err);
      }
      if (interrupted) throw new SandboxError(interrupted, "handler interrupted");
      const state = vm.getPromiseState(promise);
      if (state.type === "fulfilled") {
        const value = state.notAPromise ? vm.dump(promise) : vm.dump(state.value);
        if (!state.notAPromise) state.value.dispose();
        promise.dispose();
        // Returned while an awaited-or-not DB call is still in flight: the
        // broker treats the whole request as failed and rolls it back.
        return { value, pendingRpc };
      }
      if (state.type === "rejected") {
        const err = guestError(vm, state.error);
        state.error.dispose();
        promise.dispose();
        throw classify(err);
      }
      if (pendingRpc === 0) {
        // Pending forever with nothing to wait for (e.g. `new Promise(() => {})`).
        throw new SandboxError("handler_stalled", "handler awaits a promise that never settles");
      }
      const remaining = wallDeadline - Date.now();
      if (remaining <= 0) throw new SandboxError("execution_deadline", "wall deadline exceeded");
      await new Promise((resolve) => {
        wake = resolve;
        setTimeout(resolve, remaining).unref?.();
      });
    }
  } finally {
    // No dispose: the whole WASM instance is dropped and garbage collected,
    // and freeing a runtime that still owns guest objects aborts the module.
    alive = false;
  }
}
