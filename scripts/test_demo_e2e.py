"""Automated End-to-End Test for the Demonstration Scenario.

Starts backend and demo microservices subprocesses, executes run_demonstration(),
verifies all steps succeed, and terminates the subprocesses cleanly.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable

for p in (ROOT_DIR, ROOT_DIR / "backend", ROOT_DIR / "demo-microservices"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import httpx
from scripts.run_demo_scenario import run_demonstration


async def wait_for_health(url: str, timeout: float = 35.0) -> bool:
    t0 = time.time()
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() - t0 < timeout:
            try:
                res = await client.get(url)
                if res.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def main():
    procs = []
    try:
        print("Launching TraceMind backend...", flush=True)
        backend_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT_DIR / "backend"),
        )
        procs.append(("Backend", backend_proc))

        print("Launching demo microservices...", flush=True)
        demo_proc = subprocess.Popen(
            [PYTHON_EXE, "run_all.py"],
            cwd=str(ROOT_DIR / "demo-microservices"),
        )
        procs.append(("Microservices", demo_proc))

        print("Waiting for services to become healthy...", flush=True)
        b_ok = await wait_for_health("http://127.0.0.1:8000/api/v1/health")
        o_ok = await wait_for_health("http://127.0.0.1:8001/health")
        p_ok = await wait_for_health("http://127.0.0.1:8002/health")
        i_ok = await wait_for_health("http://127.0.0.1:8003/health")

        if not (b_ok and o_ok and p_ok and i_ok):
            print("ERROR: Not all services became healthy in time!", flush=True)
            print(f"Backend: {b_ok} (poll={backend_proc.poll()}), Order: {o_ok}, Payment: {p_ok}, Inventory: {i_ok} (demo_poll={demo_proc.poll()})", flush=True)
            sys.exit(1)

        print("All services healthy! Executing demonstration scenario in strict automated mode...\n", flush=True)
        await run_demonstration(mode="auto")
        print("\nDEMONSTRATION SCENARIO COMPLETED SUCCESSFULLY WITH STRICT ASSERTIONS!")

    finally:
        print("\nTearing down test subprocesses...")
        for name, proc in procs:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            print(f"Stopped {name}")


if __name__ == "__main__":
    asyncio.run(main())
