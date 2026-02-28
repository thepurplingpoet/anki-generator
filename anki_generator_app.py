#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║  Anki Deck Generator — Desktop Web App                       ║
║  Double-click this file to launch the app in your browser.   ║
║  Everything is auto-installed — no tech skills needed.        ║
╚═══════════════════════════════════════════════════════════════╝

This wraps https://github.com/thepurplingpoet/anki-generator
into a friendly local web application. All command-line arguments
become GUI settings. Dependencies, Ollama, and models are
auto-installed as needed.

Requirements: Python 3.9+ (that's it — everything else is automatic)
"""

import subprocess
import sys
import os
import json
import re
import threading
import time
import webbrowser
import tempfile
import shutil
import platform
import socket
import hashlib
import base64
import signal
import traceback
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: BOOTSTRAP — Install Python dependencies before importing anything
# ═══════════════════════════════════════════════════════════════════════════════

REQUIRED_PACKAGES = {
    "flask": "flask",
    "pdfplumber": "pdfplumber>=0.10.0",
    "pypdf": "pypdf>=3.0.0",
    "docx": "python-docx>=0.8.11",
}

def _pip_install(package_spec: str):
    """Install a package via pip, quietly."""
    cmd = [sys.executable, "-m", "pip", "install", package_spec, "--quiet"]
    # Add --break-system-packages on Linux if needed
    if platform.system() == "Linux":
        cmd.append("--break-system-packages")
    subprocess.run(cmd, capture_output=True)

def ensure_python_deps():
    """Check and install all required Python packages."""
    missing = []
    for import_name, pip_spec in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append((import_name, pip_spec))

    if missing:
        print("📦 Installing required Python packages...")
        for import_name, pip_spec in missing:
            print(f"   Installing {pip_spec}...")
            _pip_install(pip_spec)
        # Verify
        for import_name, pip_spec in missing:
            try:
                __import__(import_name)
                print(f"   ✓ {import_name}")
            except ImportError:
                print(f"   ✗ Failed to install {import_name}. Try: pip install {pip_spec}")
                sys.exit(1)

ensure_python_deps()

# Now we can safely import everything
from flask import Flask, request, jsonify, send_file, send_from_directory
import pdfplumber
from pypdf import PdfReader

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: CLONE / LOCATE the anki_generator module
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = Path(__file__).parent.resolve()
REPO_DIR = APP_DIR / "anki-generator"
GENERATOR_FILE = REPO_DIR / "anki_generator.py"
UPLOAD_DIR = APP_DIR / "uploads"
OUTPUT_DIR = APP_DIR / "output"

def ensure_generator():
    """Clone the anki-generator repo if not already present."""
    if GENERATOR_FILE.exists():
        return
    print("📥 Downloading Anki Generator...")
    try:
        subprocess.run(
            ["git", "clone", "https://github.com/thepurplingpoet/anki-generator.git", str(REPO_DIR)],
            capture_output=True, check=True
        )
        print("   ✓ Downloaded")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("   ✗ git clone failed. Please install git or download the repo manually.")
        sys.exit(1)

ensure_generator()

# Import the generator module dynamically
import importlib.util
spec = importlib.util.spec_from_file_location("anki_generator", str(GENERATOR_FILE))
anki_gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anki_gen)

# Create working dirs
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: SYSTEM DEPENDENCY HELPERS (Ollama, Poppler)
# ═══════════════════════════════════════════════════════════════════════════════

def check_ollama_installed() -> bool:
    """Check if Ollama CLI is installed."""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def check_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False

def get_ollama_models() -> list:
    """Get list of installed Ollama models."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []

def install_ollama() -> dict:
    """Attempt to install Ollama automatically."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            # Try brew first
            result = subprocess.run(["brew", "install", "ollama"], capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return {"success": True, "message": "Installed Ollama via Homebrew"}
            # Fallback: direct download
            result = subprocess.run(
                ["curl", "-fsSL", "https://ollama.com/install.sh"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                install_result = subprocess.run(
                    ["sh", "-c", result.stdout],
                    capture_output=True, text=True, timeout=300
                )
                if install_result.returncode == 0:
                    return {"success": True, "message": "Installed Ollama via install script"}
        elif system == "Linux":
            result = subprocess.run(
                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return {"success": True, "message": "Installed Ollama via install script"}
        elif system == "Windows":
            return {"success": False, "message": "Please install Ollama manually from https://ollama.com/download"}
    except Exception as e:
        return {"success": False, "message": f"Installation failed: {str(e)}"}
    return {"success": False, "message": "Could not auto-install Ollama. Visit https://ollama.com/download"}

def start_ollama_server() -> bool:
    """Start Ollama server in the background."""
    if check_ollama_running():
        return True
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        # Wait for it to come up
        for _ in range(15):
            time.sleep(1)
            if check_ollama_running():
                return True
    except Exception:
        pass
    return False

def pull_ollama_model(model: str) -> dict:
    """Pull/download an Ollama model."""
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            return {"success": True, "message": f"Model '{model}' is ready"}
        return {"success": False, "message": result.stderr or "Pull failed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Download timed out (model may be very large)"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def check_poppler_installed() -> bool:
    try:
        subprocess.run(["pdfimages", "-v"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

def install_poppler() -> dict:
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(["brew", "install", "poppler"], capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return {"success": True, "message": "Installed poppler via Homebrew"}
        elif system == "Linux":
            result = subprocess.run(
                ["sudo", "apt", "install", "-y", "poppler-utils"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                return {"success": True, "message": "Installed poppler-utils via apt"}
        elif system == "Windows":
            return {"success": False, "message": "Download poppler from https://github.com/oschwartz10612/poppler-windows/releases"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    return {"success": False, "message": "Could not auto-install poppler"}


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: JOB RUNNER — Runs the generator in a background thread
# ═══════════════════════════════════════════════════════════════════════════════

jobs = {}  # job_id -> {status, progress, logs, result, ...}

class LogCapture:
    """Captures print output to store in job logs."""
    def __init__(self, job_id):
        self.job_id = job_id
        self.original_stdout = sys.stdout
        self.buffer = []

    def write(self, text):
        if text.strip():
            self.buffer.append(text.rstrip())
            if self.job_id in jobs:
                jobs[self.job_id]["logs"] = list(self.buffer)
        self.original_stdout.write(text)

    def flush(self):
        self.original_stdout.flush()


def run_generation_job(job_id: str, filepath: str, settings: dict):
    """Run the full anki generation pipeline in a background thread."""
    job = jobs[job_id]
    job["status"] = "running"
    job["progress"] = "Starting..."

    log = LogCapture(job_id)
    old_stdout = sys.stdout
    sys.stdout = log

    try:
        input_path = Path(filepath)
        ext = input_path.suffix.lower()

        # Parse settings
        backend = settings.get("backend", "ollama")
        model = settings.get("model", "llama3.1:8b")
        low_mem = settings.get("low_mem", False)
        max_cards = settings.get("max_cards") or None
        cards_per_page = settings.get("cards_per_page") or None
        pages = settings.get("pages", "").strip() or None
        deck_name = settings.get("deck_name", "").strip() or input_path.stem.replace('_', ' ').replace('-', ' ').title()
        api_key = settings.get("api_key", "").strip() or None

        if max_cards:
            max_cards = int(max_cards)
        if cards_per_page:
            cards_per_page = int(cards_per_page)

        # Parse page range
        page_range = None
        if pages:
            parts = pages.split('-')
            if len(parts) == 2:
                page_range = (int(parts[0]), int(parts[1]))

        # Auto-setup for Ollama backend
        if backend == "ollama":
            job["progress"] = "Checking Ollama..."
            if not check_ollama_installed():
                job["progress"] = "Installing Ollama..."
                result = install_ollama()
                if not result["success"]:
                    raise Exception(f"Ollama install failed: {result['message']}")

            if not check_ollama_running():
                job["progress"] = "Starting Ollama server..."
                if not start_ollama_server():
                    raise Exception("Could not start Ollama server")

            installed_models = get_ollama_models()
            model_base = model.split(":")[0]
            if not any(model_base in m for m in installed_models):
                job["progress"] = f"Downloading model '{model}'... (this may take a few minutes)"
                result = pull_ollama_model(model)
                if not result["success"]:
                    raise Exception(f"Model download failed: {result['message']}")

        # Step 1: Read document
        job["progress"] = "Reading document..."
        if ext == '.pdf':
            text, images = anki_gen.read_pdf(str(input_path), page_range=page_range)
        elif ext in ('.docx', '.doc'):
            text, images = anki_gen.read_docx(str(input_path))
        else:
            text, images = anki_gen.read_txt(str(input_path))

        if not text.strip():
            raise Exception("No text could be extracted from the file.")

        # Filter boilerplate
        text = anki_gen.filter_content(text)
        if not text.strip():
            raise Exception("All content was filtered out. Try targeting specific pages.")

        # Step 2: Generate cards
        job["progress"] = "Generating flashcards... (this may take a while)"
        image_names = [img["name"] for img in images] if images else []

        if backend == "offline":
            cards = anki_gen.generate_cards_offline(text)
        elif backend == "ollama":
            cards = anki_gen.call_ollama(
                text, has_images=bool(images), image_names=image_names,
                model=model, max_cards=max_cards, low_mem=low_mem,
                cards_per_page=cards_per_page
            )
        elif backend == "claude":
            cards = anki_gen.call_claude_api(
                text, has_images=bool(images), image_names=image_names,
                api_key=api_key, max_cards=max_cards
            )
        else:
            raise Exception(f"Unknown backend: {backend}")

        if not cards:
            raise Exception("No flashcards were generated. Try a different model or settings.")

        # Step 2b: Attach images
        if images:
            job["progress"] = "Attaching images to cards..."
            cards = anki_gen.attach_images_to_cards(cards, images)

        # Step 3: Export
        job["progress"] = "Exporting CSV..."
        output_name = f"{input_path.stem}_anki_deck.csv"
        output_path = str(OUTPUT_DIR / output_name)
        image_dir = str(OUTPUT_DIR / f"{input_path.stem}_media") if images else None

        anki_gen.export_to_csv(cards, output_path, images, image_dir)

        # Build result
        type_counts = {}
        for c in cards:
            t = c.get("front_type", "question")
            type_counts[t] = type_counts.get(t, 0) + 1

        all_tags = set()
        for c in cards:
            all_tags.update(c.get("tags", []))

        job["status"] = "done"
        job["progress"] = "Complete!"
        job["result"] = {
            "csv_file": output_name,
            "card_count": len(cards),
            "card_types": type_counts,
            "topics": sorted(list(all_tags))[:20],
            "image_count": len(images),
            "deck_name": deck_name,
            "has_media": image_dir is not None and os.path.isdir(image_dir or ""),
            "media_dir": f"{input_path.stem}_media" if image_dir else None,
            "sample_cards": [
                {"front": c["front"][:200], "back": c["back"][:200], "tags": c.get("tags", [])}
                for c in cards[:5]
            ]
        }

    except Exception as e:
        job["status"] = "error"
        job["progress"] = f"Error: {str(e)}"
        job["error"] = str(e)
        traceback.print_exc()
    finally:
        sys.stdout = old_stdout


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: FLASK WEB APP
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anki Deck Generator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0c0c0f;
  --bg-card: #141418;
  --bg-card-hover: #1a1a20;
  --bg-input: #1e1e26;
  --border: #2a2a35;
  --border-focus: #5b6ef5;
  --text: #e8e8ed;
  --text-dim: #8888a0;
  --text-faint: #555568;
  --accent: #5b6ef5;
  --accent-glow: rgba(91, 110, 245, 0.15);
  --success: #4ade80;
  --error: #f87171;
  --warning: #fbbf24;
  --radius: 12px;
  --radius-sm: 8px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: 'DM Sans', -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Subtle animated background */
body::before {
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(91, 110, 245, 0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(139, 92, 246, 0.04) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

.container {
  max-width: 860px;
  margin: 0 auto;
  padding: 40px 24px 80px;
  position: relative;
  z-index: 1;
}

/* Header */
.header {
  text-align: center;
  margin-bottom: 48px;
}
.header h1 {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--text) 0%, var(--text-dim) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.header p {
  color: var(--text-dim);
  font-size: 0.95rem;
  line-height: 1.5;
}
.header .badge {
  display: inline-block;
  margin-top: 12px;
  padding: 4px 12px;
  background: var(--accent-glow);
  border: 1px solid rgba(91, 110, 245, 0.2);
  border-radius: 20px;
  font-size: 0.78rem;
  color: var(--accent);
  font-weight: 500;
}

/* Status bar */
.status-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 32px;
  flex-wrap: wrap;
}
.status-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 0.82rem;
  color: var(--text-dim);
  transition: all 0.2s;
}
.status-chip .dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--text-faint);
  transition: background 0.3s;
}
.status-chip .dot.green { background: var(--success); box-shadow: 0 0 6px rgba(74, 222, 128, 0.4); }
.status-chip .dot.red { background: var(--error); }
.status-chip .dot.yellow { background: var(--warning); }
.status-chip .dot.pulse { animation: pulse 1.5s ease infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Cards / Sections */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 28px;
  margin-bottom: 20px;
  transition: border-color 0.2s;
}
.card:hover { border-color: #3a3a48; }
.card h2 {
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.card h2 .num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  background: var(--accent-glow);
  border: 1px solid rgba(91, 110, 245, 0.25);
  border-radius: 8px;
  font-size: 0.78rem;
  color: var(--accent);
  font-weight: 700;
  flex-shrink: 0;
}

/* Form elements */
label {
  display: block;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-dim);
  margin-bottom: 6px;
}
label .hint {
  font-weight: 400;
  color: var(--text-faint);
  font-size: 0.78rem;
}

input[type="text"], input[type="number"], input[type="password"], select {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-family: inherit;
  font-size: 0.9rem;
  transition: border-color 0.2s, box-shadow 0.2s;
  outline: none;
}
input:focus, select:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
select { cursor: pointer; }
select option { background: var(--bg-card); }

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.form-group { margin-bottom: 16px; }

/* Toggle / Checkbox */
.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid rgba(42, 42, 53, 0.5);
}
.toggle-row:last-child { border-bottom: none; }
.toggle-label {
  font-size: 0.9rem;
  color: var(--text);
}
.toggle-label span {
  display: block;
  font-size: 0.78rem;
  color: var(--text-faint);
  margin-top: 2px;
}
.toggle {
  position: relative;
  width: 44px; height: 24px;
  cursor: pointer;
}
.toggle input { display: none; }
.toggle .slider {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: 12px;
  transition: all 0.25s;
}
.toggle .slider::before {
  content: '';
  position: absolute;
  width: 18px; height: 18px;
  left: 2px; bottom: 2px;
  background: var(--text-dim);
  border-radius: 50%;
  transition: all 0.25s;
}
.toggle input:checked + .slider {
  background: var(--accent);
  border-color: var(--accent);
}
.toggle input:checked + .slider::before {
  transform: translateX(20px);
  background: white;
}

/* File upload zone */
.upload-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.25s;
  position: relative;
  overflow: hidden;
}
.upload-zone:hover, .upload-zone.dragover {
  border-color: var(--accent);
  background: var(--accent-glow);
}
.upload-zone.has-file {
  border-color: var(--success);
  border-style: solid;
  background: rgba(74, 222, 128, 0.05);
  padding: 24px;
}
.upload-zone .icon {
  font-size: 2.5rem;
  margin-bottom: 12px;
}
.upload-zone .main-text {
  font-size: 1rem;
  font-weight: 500;
  margin-bottom: 4px;
}
.upload-zone .sub-text {
  font-size: 0.82rem;
  color: var(--text-faint);
}
.upload-zone input[type="file"] {
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  opacity: 0;
  cursor: pointer;
}
.file-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.file-info .file-icon { font-size: 1.8rem; }
.file-info .file-details { text-align: left; }
.file-info .file-name { font-weight: 600; font-size: 0.95rem; }
.file-info .file-meta { font-size: 0.8rem; color: var(--text-dim); }
.file-info .remove-btn {
  margin-left: auto;
  background: none;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-dim);
  padding: 4px 10px;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.2s;
}
.file-info .remove-btn:hover {
  border-color: var(--error);
  color: var(--error);
}

/* Buttons */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 14px 24px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}
.btn-primary:hover:not(:disabled) {
  background: #4d5fe0;
  transform: translateY(-1px);
  box-shadow: 0 4px 20px rgba(91, 110, 245, 0.3);
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-family: inherit;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  text-decoration: none;
}
.btn-secondary:hover {
  border-color: var(--accent);
  background: var(--accent-glow);
}
.btn-action-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* Progress / Log panel */
.progress-panel {
  display: none;
}
.progress-panel.visible { display: block; }
.progress-bar-track {
  height: 4px;
  background: var(--bg-input);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 16px;
}
.progress-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.5s ease;
  width: 0%;
}
.progress-bar-fill.indeterminate {
  width: 30%;
  animation: indeterminate 1.5s ease infinite;
}
@keyframes indeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
.progress-status {
  font-size: 0.9rem;
  font-weight: 500;
  margin-bottom: 12px;
}
.log-output {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
  max-height: 280px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  line-height: 1.6;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-word;
}

/* Results panel */
.results-panel { display: none; }
.results-panel.visible { display: block; }
.result-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.stat-box {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
  text-align: center;
}
.stat-box .value {
  font-size: 1.8rem;
  font-weight: 700;
  color: var(--accent);
}
.stat-box .label {
  font-size: 0.78rem;
  color: var(--text-faint);
  margin-top: 4px;
}
.sample-cards {
  margin-top: 16px;
}
.sample-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  margin-bottom: 8px;
}
.sample-card .sc-front {
  font-weight: 600;
  font-size: 0.88rem;
  margin-bottom: 6px;
}
.sample-card .sc-back {
  font-size: 0.82rem;
  color: var(--text-dim);
}
.sample-card .sc-tags {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.sample-card .sc-tags span {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: var(--accent-glow);
  border-radius: 10px;
  color: var(--accent);
}

/* Claude API key section */
.api-key-section {
  display: none;
}
.api-key-section.visible { display: block; }

/* Install buttons in status */
.install-btn {
  background: none;
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.75rem;
  cursor: pointer;
  font-family: inherit;
  margin-left: 6px;
  transition: all 0.2s;
}
.install-btn:hover {
  background: var(--accent);
  color: white;
}
.install-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Responsive */
@media (max-width: 600px) {
  .container { padding: 24px 16px 60px; }
  .form-row { grid-template-columns: 1fr; }
  .header h1 { font-size: 1.5rem; }
}
</style>
</head>
<body>
<div class="container">
  <!-- HEADER -->
  <div class="header">
    <h1>📚 Anki Deck Generator</h1>
    <p>Turn any PDF, DOCX, or TXT file into Anki flashcards — powered by AI</p>
    <div class="badge">Local-first • No data leaves your machine with Ollama</div>
  </div>

  <!-- STATUS BAR -->
  <div class="status-bar" id="statusBar">
    <div class="status-chip" id="statusOllama">
      <span class="dot" id="dotOllama"></span>
      <span id="labelOllama">Ollama: checking...</span>
    </div>
    <div class="status-chip" id="statusPoppler">
      <span class="dot" id="dotPoppler"></span>
      <span id="labelPoppler">Poppler: checking...</span>
    </div>
  </div>

  <!-- STEP 1: UPLOAD -->
  <div class="card">
    <h2><span class="num">1</span> Upload Your Document</h2>
    <div class="upload-zone" id="uploadZone">
      <div id="uploadPrompt">
        <div class="icon">📄</div>
        <div class="main-text">Drop your file here or click to browse</div>
        <div class="sub-text">PDF, DOCX, TXT, or Markdown • No size limit</div>
      </div>
      <div id="fileInfo" style="display:none;">
        <div class="file-info">
          <span class="file-icon" id="fileIcon">📕</span>
          <div class="file-details">
            <div class="file-name" id="fileName"></div>
            <div class="file-meta" id="fileMeta"></div>
          </div>
          <button class="remove-btn" id="removeFile" type="button">Remove</button>
        </div>
      </div>
      <input type="file" id="fileInput" accept=".pdf,.docx,.doc,.txt,.md">
    </div>
  </div>

  <!-- STEP 2: SETTINGS -->
  <div class="card">
    <h2><span class="num">2</span> Settings</h2>

    <div class="form-group">
      <label>AI Backend</label>
      <select id="backend">
        <option value="ollama" selected>🦙 Ollama — Local AI (free, private)</option>
        <option value="claude">🤖 Claude API — Cloud AI (highest quality, needs API key)</option>
        <option value="offline">⚡ Offline — Rule-based (instant, no AI)</option>
      </select>
    </div>

    <!-- Ollama model selector -->
    <div id="ollamaSettings">
      <div class="form-group">
        <label>Model <span class="hint">— smaller models are faster, larger are smarter</span></label>
        <select id="model">
          <option value="phi3:mini">phi3:mini — Tiny & fast (1.6 GB, good for 8GB Macs)</option>
          <option value="mistral">mistral — Fast, decent quality (4.1 GB)</option>
          <option value="llama3.1:8b" selected>llama3.1:8b — Default, reliable (4.7 GB)</option>
          <option value="qwen2.5:7b">qwen2.5:7b — Best JSON structure (4.4 GB)</option>
          <option value="gemma2:9b">gemma2:9b — Strong reasoning (5.4 GB)</option>
        </select>
      </div>
      <div class="toggle-row">
        <div class="toggle-label">
          Low Memory Mode
          <span>For 8GB Macs — processes in smaller chunks</span>
        </div>
        <label class="toggle">
          <input type="checkbox" id="lowMem">
          <span class="slider"></span>
        </label>
      </div>
    </div>

    <!-- Claude API key -->
    <div class="api-key-section" id="claudeSettings">
      <div class="form-group">
        <label>Anthropic API Key</label>
        <input type="password" id="apiKey" placeholder="sk-ant-...">
      </div>
    </div>

    <div class="form-row">
      <div class="form-group">
        <label>Deck Name <span class="hint">— blank = auto from filename</span></label>
        <input type="text" id="deckName" placeholder="e.g. Biology 101">
      </div>
      <div class="form-group">
        <label>Page Range <span class="hint">— PDFs only, e.g. 1-50</span></label>
        <input type="text" id="pages" placeholder="All pages">
      </div>
    </div>

    <div class="form-row">
      <div class="form-group">
        <label>Max Cards <span class="hint">— blank = auto</span></label>
        <input type="number" id="maxCards" placeholder="Auto" min="1" max="5000">
      </div>
      <div class="form-group">
        <label>Cards Per Page <span class="hint">— e.g. 5</span></label>
        <input type="number" id="cardsPerPage" placeholder="Auto" min="1" max="50">
      </div>
    </div>

    <div class="toggle-row">
      <div class="toggle-label">
        Verbose Logging
        <span>Show detailed progress in the log panel</span>
      </div>
      <label class="toggle">
        <input type="checkbox" id="verbose" checked>
        <span class="slider"></span>
      </label>
    </div>
  </div>

  <!-- STEP 3: GENERATE -->
  <div class="card">
    <h2><span class="num">3</span> Generate</h2>
    <button class="btn-primary" id="generateBtn" disabled>
      <span id="btnText">Select a file to begin</span>
    </button>

    <!-- Progress -->
    <div class="progress-panel" id="progressPanel">
      <div style="margin-top: 20px;"></div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill indeterminate" id="progressBar"></div>
      </div>
      <div class="progress-status" id="progressStatus">Starting...</div>
      <div class="log-output" id="logOutput"></div>
    </div>

    <!-- Results -->
    <div class="results-panel" id="resultsPanel">
      <div style="margin-top: 20px;"></div>
      <div class="result-stats" id="resultStats"></div>
      <div class="btn-action-row">
        <a class="btn-secondary" id="downloadCSV" href="#" download>📥 Download CSV</a>
        <a class="btn-secondary" id="downloadMedia" href="#" download style="display:none;">🖼️ Download Media</a>
        <button class="btn-secondary" id="newJobBtn">🔄 Generate Another</button>
      </div>
      <div class="sample-cards" id="sampleCards"></div>
    </div>
  </div>
</div>

<script>
// ─── State ───
let selectedFile = null;
let currentJobId = null;
let pollTimer = null;

// ─── DOM refs ───
const $ = id => document.getElementById(id);
const uploadZone = $('uploadZone');
const fileInput = $('fileInput');
const generateBtn = $('generateBtn');
const btnText = $('btnText');
const backend = $('backend');
const progressPanel = $('progressPanel');
const resultsPanel = $('resultsPanel');
const logOutput = $('logOutput');

// ─── Check system status on load ───
async function checkStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    // Ollama
    const dotO = $('dotOllama');
    const labO = $('labelOllama');
    if (data.ollama_running) {
      dotO.className = 'dot green';
      labO.textContent = `Ollama: running (${data.ollama_models.length} models)`;
    } else if (data.ollama_installed) {
      dotO.className = 'dot yellow';
      labO.innerHTML = `Ollama: installed but not running`;
    } else {
      dotO.className = 'dot red';
      labO.innerHTML = `Ollama: not installed <button class="install-btn" onclick="installOllama(this)">Install</button>`;
    }

    // Poppler
    const dotP = $('dotPoppler');
    const labP = $('labelPoppler');
    if (data.poppler_installed) {
      dotP.className = 'dot green';
      labP.textContent = 'Poppler: installed';
    } else {
      dotP.className = 'dot yellow';
      labP.innerHTML = `Poppler: not found (optional) <button class="install-btn" onclick="installPoppler(this)">Install</button>`;
    }
  } catch (e) {
    console.error('Status check failed:', e);
  }
}

async function installOllama(btn) {
  btn.disabled = true;
  btn.textContent = 'Installing...';
  try {
    const res = await fetch('/api/install-ollama', { method: 'POST' });
    const data = await res.json();
    alert(data.message);
    checkStatus();
  } catch (e) { alert('Installation failed: ' + e.message); }
}

async function installPoppler(btn) {
  btn.disabled = true;
  btn.textContent = 'Installing...';
  try {
    const res = await fetch('/api/install-poppler', { method: 'POST' });
    const data = await res.json();
    alert(data.message);
    checkStatus();
  } catch (e) { alert('Installation failed: ' + e.message); }
}

// ─── File handling ───
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function setFile(file) {
  if (!file) return;
  const validExts = ['.pdf', '.docx', '.doc', '.txt', '.md'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!validExts.includes(ext)) {
    alert('Unsupported file type. Please use PDF, DOCX, TXT, or Markdown.');
    return;
  }
  selectedFile = file;
  const icons = { '.pdf': '📕', '.docx': '📘', '.doc': '📘', '.txt': '📄', '.md': '📝' };
  $('fileIcon').textContent = icons[ext] || '📄';
  $('fileName').textContent = file.name;
  $('fileMeta').textContent = `${formatBytes(file.size)} • ${ext.toUpperCase().slice(1)}`;
  $('uploadPrompt').style.display = 'none';
  $('fileInfo').style.display = 'block';
  uploadZone.classList.add('has-file');
  generateBtn.disabled = false;
  btnText.textContent = '🚀 Generate Flashcards';
}

function clearFile() {
  selectedFile = null;
  fileInput.value = '';
  $('uploadPrompt').style.display = '';
  $('fileInfo').style.display = 'none';
  uploadZone.classList.remove('has-file');
  generateBtn.disabled = true;
  btnText.textContent = 'Select a file to begin';
}

fileInput.addEventListener('change', e => setFile(e.target.files[0]));
$('removeFile').addEventListener('click', e => { e.stopPropagation(); clearFile(); });

uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});

// ─── Backend switching ───
backend.addEventListener('change', () => {
  const val = backend.value;
  $('ollamaSettings').style.display = val === 'ollama' ? '' : 'none';
  $('claudeSettings').className = val === 'claude' ? 'api-key-section visible' : 'api-key-section';
});

// ─── Generate ───
generateBtn.addEventListener('click', async () => {
  if (!selectedFile || generateBtn.disabled) return;

  // Validate
  if (backend.value === 'claude' && !$('apiKey').value.trim()) {
    alert('Please enter your Anthropic API key for the Claude backend.');
    $('apiKey').focus();
    return;
  }

  // Upload file
  generateBtn.disabled = true;
  btnText.textContent = 'Uploading...';
  resultsPanel.classList.remove('visible');

  const formData = new FormData();
  formData.append('file', selectedFile);
  formData.append('settings', JSON.stringify({
    backend: backend.value,
    model: $('model').value,
    low_mem: $('lowMem').checked,
    max_cards: $('maxCards').value || null,
    cards_per_page: $('cardsPerPage').value || null,
    pages: $('pages').value || '',
    deck_name: $('deckName').value || '',
    api_key: $('apiKey').value || '',
    verbose: $('verbose').checked,
  }));

  try {
    const res = await fetch('/api/generate', { method: 'POST', body: formData });
    const data = await res.json();

    if (data.error) {
      alert('Error: ' + data.error);
      generateBtn.disabled = false;
      btnText.textContent = '🚀 Generate Flashcards';
      return;
    }

    currentJobId = data.job_id;
    progressPanel.classList.add('visible');
    logOutput.textContent = '';
    $('progressStatus').textContent = 'Starting...';
    btnText.textContent = 'Generating...';

    // Poll for progress
    pollTimer = setInterval(pollProgress, 1000);

  } catch (e) {
    alert('Upload failed: ' + e.message);
    generateBtn.disabled = false;
    btnText.textContent = '🚀 Generate Flashcards';
  }
});

async function pollProgress() {
  if (!currentJobId) return;
  try {
    const res = await fetch(`/api/job/${currentJobId}`);
    const job = await res.json();

    $('progressStatus').textContent = job.progress || '';
    if (job.logs && job.logs.length) {
      logOutput.textContent = job.logs.join('\n');
      logOutput.scrollTop = logOutput.scrollHeight;
    }

    if (job.status === 'done') {
      clearInterval(pollTimer);
      $('progressBar').classList.remove('indeterminate');
      $('progressBar').style.width = '100%';
      showResults(job.result);
      generateBtn.disabled = false;
      btnText.textContent = '🚀 Generate Flashcards';
    } else if (job.status === 'error') {
      clearInterval(pollTimer);
      $('progressBar').classList.remove('indeterminate');
      $('progressBar').style.width = '0%';
      $('progressStatus').textContent = '❌ ' + (job.error || 'Unknown error');
      generateBtn.disabled = false;
      btnText.textContent = '🚀 Generate Flashcards';
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

function showResults(result) {
  resultsPanel.classList.add('visible');

  // Stats
  const statsHtml = `
    <div class="stat-box"><div class="value">${result.card_count}</div><div class="label">Cards</div></div>
    <div class="stat-box"><div class="value">${result.image_count}</div><div class="label">Images</div></div>
    <div class="stat-box"><div class="value">${Object.keys(result.card_types).length}</div><div class="label">Card Types</div></div>
    <div class="stat-box"><div class="value">${result.topics.length}</div><div class="label">Topics</div></div>
  `;
  $('resultStats').innerHTML = statsHtml;

  // Download links
  $('downloadCSV').href = `/api/download/${encodeURIComponent(result.csv_file)}`;
  $('downloadCSV').download = result.csv_file;

  if (result.has_media && result.media_dir) {
    $('downloadMedia').style.display = '';
    $('downloadMedia').href = `/api/download-media/${encodeURIComponent(result.media_dir)}`;
  } else {
    $('downloadMedia').style.display = 'none';
  }

  // Sample cards
  let samplesHtml = '<h3 style="font-size:0.9rem;margin-bottom:10px;color:var(--text-dim);">Sample Cards</h3>';
  for (const card of (result.sample_cards || [])) {
    const tagsHtml = (card.tags || []).map(t => `<span>${t}</span>`).join('');
    samplesHtml += `
      <div class="sample-card">
        <div class="sc-front">Q: ${escapeHtml(card.front)}</div>
        <div class="sc-back">A: ${escapeHtml(card.back)}</div>
        ${tagsHtml ? `<div class="sc-tags">${tagsHtml}</div>` : ''}
      </div>`;
  }
  $('sampleCards').innerHTML = samplesHtml;
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

$('newJobBtn').addEventListener('click', () => {
  resultsPanel.classList.remove('visible');
  progressPanel.classList.remove('visible');
  $('progressBar').classList.add('indeterminate');
  $('progressBar').style.width = '';
});

// Init
checkStatus();
setInterval(checkStatus, 30000);
</script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML_PAGE

@app.route('/api/status')
def api_status():
    return jsonify({
        "ollama_installed": check_ollama_installed(),
        "ollama_running": check_ollama_running(),
        "ollama_models": get_ollama_models(),
        "poppler_installed": check_poppler_installed(),
        "platform": platform.system(),
    })

@app.route('/api/install-ollama', methods=['POST'])
def api_install_ollama():
    result = install_ollama()
    if result["success"]:
        start_ollama_server()
    return jsonify(result)

@app.route('/api/install-poppler', methods=['POST'])
def api_install_poppler():
    return jsonify(install_poppler())

@app.route('/api/generate', methods=['POST'])
def api_generate():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    settings = json.loads(request.form.get('settings', '{}'))

    # Save uploaded file
    safe_name = re.sub(r'[^\w\.\-]', '_', file.filename)
    filepath = str(UPLOAD_DIR / safe_name)
    file.save(filepath)

    # Create job
    job_id = hashlib.md5(f"{filepath}{time.time()}".encode()).hexdigest()[:12]
    jobs[job_id] = {
        "status": "queued",
        "progress": "Queued...",
        "logs": [],
        "result": None,
        "error": None,
    }

    # Run in background thread
    thread = threading.Thread(target=run_generation_job, args=(job_id, filepath, settings), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})

@app.route('/api/job/<job_id>')
def api_job_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])

@app.route('/api/download/<filename>')
def api_download(filename):
    safe = re.sub(r'[^\w\.\-]', '_', filename)
    filepath = OUTPUT_DIR / safe
    if filepath.exists():
        return send_file(str(filepath), as_attachment=True)
    return "File not found", 404

@app.route('/api/download-media/<dirname>')
def api_download_media(dirname):
    """Zip and download the media folder."""
    safe = re.sub(r'[^\w\.\-]', '_', dirname)
    media_dir = OUTPUT_DIR / safe
    if not media_dir.is_dir():
        return "Media folder not found", 404

    zip_path = str(OUTPUT_DIR / f"{safe}.zip")
    shutil.make_archive(str(OUTPUT_DIR / safe), 'zip', str(media_dir))
    return send_file(zip_path, as_attachment=True, download_name=f"{safe}.zip")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6: LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def open_browser(port):
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")

if __name__ == "__main__":
    port = find_free_port()

    print()
    print("╔═══════════════════════════════════════════════════════╗")
    print("║   📚 Anki Deck Generator — Web App                   ║")
    print(f"║   🌐 Open: http://localhost:{port:<24}║")
    print("║   🛑 Press Ctrl+C to stop                            ║")
    print("╚═══════════════════════════════════════════════════════╝")
    print()

    # Open browser automatically
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    # Run Flask (suppress noisy logs unless debugging)
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
