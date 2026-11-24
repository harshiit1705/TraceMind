"""TraceMind Multi-Service Process Orchestrator.

Spins up and coordinates all local services required for the live interviewer demo:
1. TraceMind FastAPI Backend (Port 8000)
2. Order Microservice (Port 8001)
3. Payment Microservice (Port 8002)
4. Inventory Microservice (Port 8003)
5. TraceMind Vite Frontend (Port 5173)

Monitors stdout/stderr and performs health check polling until all services are healthy.
Press Ctrl+C to stop all services cleanly.
"""

import asyncio
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a local port is already bound by another process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


async def check_health(url: str, timeout: float = 2.0) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception:
        return False


def main():
    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{GREEN} Starting TraceMind Full-Stack Demonstration Environment...{RESET}")
    print(f"{BOLD}{CYAN}═══════════════════════════════════════════════════════════════════════{RESET}\n")

    # Pre-flight check: ensure required ports are free
    required_ports = [
        (8000, "TraceMind Backend"),
        (8001, "Order Service"),
        (8002, "Payment Service"),
        (8003, "Inventory Service"),
        (5173, "Vite Frontend"),
    ]
    conflicts = []
    for port, label in required_ports:
        if is_port_in_use(port):
            conflicts.append((port, label))

    if conflicts:
        print(f"{RED}{BOLD}ERROR: Cannot start demonstration environment because ports are already in use:{RESET}")
        for port, label in conflicts:
            print(f"  {RED}✘{RESET} Port {BOLD}{port}{RESET} ({label}) is already occupied.")
        print(f"\n{BOLD}Please terminate existing processes using these ports before starting.{RESET}")
        if any(p == 5173 for p, _ in conflicts):
            print(f"{CYAN}Note: Vite frontend strictly requires port 5173 to match configured CORS and redirect policies.{RESET}")
        sys.exit(1)

    backend_dir = ROOT_DIR / "backend"
    frontend_dir = ROOT_DIR / "frontend"
    if not shutil.which("npm.cmd" if os.name == "nt" else "npm"):
        print(f"{RED}{BOLD}ERROR: Node.js/npm was not found on PATH.{RESET}")
        sys.exit(1)
    if not (frontend_dir / "node_modules").exists():
        print(f"{RED}{BOLD}ERROR: Frontend dependencies are missing. Run 'npm ci' inside frontend first.{RESET}")
        sys.exit(1)

    print(f"{CYAN}▶{RESET} Applying database migrations (Alembic upgrade head)...")
    migration = subprocess.run(
        [PYTHON_EXE, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
    )
    if migration.returncode != 0:
        print(f"{RED}{BOLD}ERROR: Database migration failed. Check backend/.env and database availability.{RESET}")
        sys.exit(migration.returncode)

    processes = {}

    try:
        # 1. Start TraceMind Backend (:8000)
        print(f" {CYAN}▶{RESET} Launching TraceMind FastAPI Backend on port 8000...")
        backend_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT_DIR / "backend"),
        )
        processes["Backend (:8000)"] = backend_proc

        # 2. Start Demo Microservices (:8001, :8002, :8003)
        print(f" {CYAN}▶{RESET} Launching Demo Microservices (Order :8001, Payment :8002, Inventory :8003)...")
        demo_proc = subprocess.Popen(
            [PYTHON_EXE, "run_all.py"],
            cwd=str(ROOT_DIR / "demo-microservices"),
        )
        processes["Microservices (:8001-8003)"] = demo_proc

        # 3. Start Frontend (:5173)
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        print(f" {CYAN}▶{RESET} Launching React Vite Frontend on port 5173...")
        frontend_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(ROOT_DIR / "frontend"),
        )
        processes["Frontend (:5173)"] = frontend_proc

        print(f"\n{BOLD}Waiting for services to become healthy...{RESET}")
        time.sleep(3)

        services = [
            ("Backend + Database", "http://127.0.0.1:8000/api/v1/ready"),
            ("Order Service", "http://127.0.0.1:8001/health"),
            ("Payment Service", "http://127.0.0.1:8002/health"),
            ("Inventory Service", "http://127.0.0.1:8003/health"),
            ("Frontend", "http://127.0.0.1:5173/"),
        ]

        failed_services = []
        for name, url in services:
            healthy = False
            for _ in range(15):
                if asyncio.run(check_health(url)):
                    healthy = True
                    break
                time.sleep(1)
            if healthy:
                print(f"  {GREEN}✔{RESET} {name:<18} is READY at {url}")
            else:
                failed_services.append(name)
                print(f"  {RED}✘{RESET} {name:<18} did not respond at {url}")

        if failed_services:
            print(f"\n{RED}{BOLD}Startup incomplete. Unhealthy services: {', '.join(failed_services)}{RESET}")
            raise SystemExit(1)

        print(f"\n{BOLD}{GREEN}All services are running!{RESET}")
        print(f"{CYAN}Open your browser at: {BOLD}http://localhost:5173{RESET}")
        print(f"To run the automated test scenario in another terminal:")
        print(f"  {BOLD}python scripts/run_demo_scenario.py{RESET}")
        print(f"\nPress Ctrl+C to shutdown all services.\n")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n{BOLD}Stopping all services...{RESET}")
    finally:
        for name, proc in processes.items():
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            print(f"  Stopped {name}")
        print(f"{GREEN}All services stopped cleanly.{RESET}")


if __name__ == "__main__":
    main()
