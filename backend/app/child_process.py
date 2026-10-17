"""Child processes of the pure parsers (`python -m app.<module>`).

Untrusted file bytes (PDF, Office, OCR input) are parsed only in a child:
it can be killed on a timeout and held to a memory limit, which a thread
cannot. Every parent goes through `child` so the child is always reaped,
whether the parent finishes, times out or is cancelled.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def child(
    module: str,
    args: Sequence[str],
    *,
    line_limit: int | None = None,
    env: Mapping[str, str] | None = None,
) -> AsyncIterator[asyncio.subprocess.Process]:
    """A running `python -m module args...` with piped stdin and stdout,
    killed and reaped on the way out if it is still alive. `env` is added
    to the parent's environment."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=_BACKEND_ROOT,
        env={**os.environ, **env} if env else None,
        # asyncio's own default line limit is 64 KiB.
        limit=line_limit or 2**16,
    )
    try:
        yield proc
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def run_child(module: str, args: Sequence[str], data: bytes, timeout: float) -> bytes | None:
    """Feed `data` to the child and return its stdout; None when it failed
    (non-zero exit or no output). Raises `TimeoutError` past `timeout`."""
    async with child(module, args) as proc:
        out, _ = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
    if proc.returncode != 0 or not out:
        return None
    return out
