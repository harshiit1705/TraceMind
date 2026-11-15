"""Utility script to create a clean, reproducible source code archive for TraceMind.

Excludes:
- Secrets, credentials, and environment files (.env, .env.*)
- Local SQLite database files (*.db, *.sqlite, *.db-shm, *.db-wal)
- Virtual environments (.venv, venv, ENV)
- Node modules (node_modules, frontend/node_modules)
- Build outputs (dist, frontend/dist)
- Caches (__pycache__, .pytest_cache, .mypy_cache)
- Version control metadata (.git)
"""

import fnmatch
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "ENV",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "dist-ssr",
    "build",
    ".idea",
    ".vscode",
}

EXCLUDE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.sqlite",
    "*.sqlite3",
    "*.tmp",
    "*.temp",
    "*.log",
    ".DS_Store",
    "Thumbs.db",
    "*.zip",
]

EXCLUDE_EXACT_FILES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
}


def should_exclude(rel_path: Path) -> bool:
    # Check directory parts
    for part in rel_path.parts[:-1]:
        if part in EXCLUDE_DIRS:
            return True

    filename = rel_path.name

    # Check exact exclusions
    if filename in EXCLUDE_EXACT_FILES:
        return True

    # Allow .env.example files
    if filename.endswith(".env.example") or filename == ".env.example":
        return False

    # Check env files
    if filename.startswith(".env"):
        return True

    # Check glob patterns
    for pat in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(filename, pat):
            return True

    return False


def create_archive(output_path: Path = None) -> Path:
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = ROOT_DIR / f"tracemind_source_{timestamp}.zip"

    print(f"Creating clean source archive: {output_path.name}...")
    included_count = 0
    excluded_count = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(ROOT_DIR):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                abs_file = Path(root) / file
                rel_file = abs_file.relative_to(ROOT_DIR)

                if should_exclude(rel_file):
                    excluded_count += 1
                    continue

                zipf.write(abs_file, str(rel_file))
                included_count += 1

    print(f"Archive successfully created: {output_path}")
    print(f"Files included: {included_count}, Files/patterns skipped: {excluded_count}")
    print(f"Archive size: {output_path.stat().st_size / (1024 * 1024):.2f} MB")
    return output_path


if __name__ == "__main__":
    archive_file = create_archive()
