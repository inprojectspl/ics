// Syntax check of a handler module without running it (used by plan/apply).
import { newQuickJSWASMModuleFromVariant } from "quickjs-emscripten-core";
import RELEASE_SYNC from "@jitl/quickjs-wasmfile-release-sync";

// JS_EVAL_TYPE_MODULE | JS_EVAL_FLAG_COMPILE_ONLY (quickjs.h)
const MODULE_COMPILE_ONLY = (1 << 0) | (1 << 5);

export async function compileOnly(code, filename) {
  const QuickJS = await newQuickJSWASMModuleFromVariant(RELEASE_SYNC);
  const runtime = QuickJS.newRuntime();
  runtime.setMemoryLimit(16 * 1024 * 1024);
  const deadline = Date.now() + 500;
  runtime.setInterruptHandler(() => Date.now() > deadline);
  const vm = runtime.newContext();
  const result = vm.evalCode(code, filename, MODULE_COMPILE_ONLY);
  if (result.error) {
    const err = vm.dump(result.error);
    throw Object.assign(new Error(err?.message ?? String(err)), { code: "syntax_error" });
  }
  // Compile-only of a module yields the module object; the instance is dropped.
}
