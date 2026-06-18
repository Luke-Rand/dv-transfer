import os
import sys
import platform
import subprocess
import urllib.request
import zipfile
import shutil
import tempfile
from pathlib import Path

# Base directories
APP_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = APP_DIR.parent
BIN_DIR = WORKSPACE_DIR / "bin"

def get_ffmpeg_paths():
    """
    Finds ffmpeg and ffprobe paths.
    Checks the system PATH first, then looks in workspace/bin/.
    Returns a tuple of (ffmpeg_path, ffprobe_path).
    Values will be absolute paths or command names, or None if not found.
    """
    ext = ".exe" if platform.system() == "Windows" else ""
    ffmpeg_name = f"ffmpeg{ext}"
    ffprobe_name = f"ffprobe{ext}"

    # 1. Check system PATH
    ffmpeg_in_path = shutil.which(ffmpeg_name) is not None
    ffprobe_in_path = shutil.which(ffprobe_name) is not None

    ffmpeg_path = ffmpeg_name if ffmpeg_in_path else None
    ffprobe_path = ffprobe_name if ffprobe_in_path else None

    # 2. Check local bin directory
    if not ffmpeg_path:
        local_ffmpeg = BIN_DIR / ffmpeg_name
        if local_ffmpeg.is_file():
            ffmpeg_path = str(local_ffmpeg)

    if not ffprobe_path:
        local_ffprobe = BIN_DIR / ffprobe_name
        if local_ffprobe.is_file():
            ffprobe_path = str(local_ffprobe)

    return ffmpeg_path, ffprobe_path

def download_ffmpeg_windows(progress_hook=None):
    """
    Downloads and installs the static release of FFmpeg for Windows into workspace/bin/.
    progress_hook is a callable: progress_hook(bytes_downloaded, total_bytes)
    """
    if platform.system() != "Windows":
        raise NotImplementedError("Automatic downloading is only supported on Windows.")

    # Gyan.dev Essentials build is reliable and smaller than full builds (~35MB)
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "ffmpeg.zip"
        
        # Download with progress callback
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                block_size = 1024 * 1024  # 1MB
                downloaded = 0
                
                with open(zip_path, 'wb') as out_file:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        out_file.write(buffer)
                        if progress_hook:
                            progress_hook(downloaded, total_size)
        except Exception as e:
            raise RuntimeError(f"Failed to download FFmpeg: {e}")

        # Extract zip
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_path)
        except Exception as e:
            raise RuntimeError(f"Failed to extract FFmpeg zip: {e}")
        
        # Locate ffmpeg.exe and ffprobe.exe in the extracted directories
        ffmpeg_src = None
        ffprobe_src = None
        for root, _, files in os.walk(temp_dir_path):
            for file in files:
                if file.lower() == "ffmpeg.exe":
                    ffmpeg_src = Path(root) / file
                elif file.lower() == "ffprobe.exe":
                    ffprobe_src = Path(root) / file
        
        if not ffmpeg_src or not ffprobe_src:
            raise FileNotFoundError("Could not locate ffmpeg.exe or ffprobe.exe inside the downloaded archive.")
            
        # Copy to local bin dir
        shutil.copy2(ffmpeg_src, BIN_DIR / "ffmpeg.exe")
        shutil.copy2(ffprobe_src, BIN_DIR / "ffprobe.exe")

def is_tool_executable(path):
    """Checks if a tool runs and returns exit code 0."""
    try:
        subprocess.run([path, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False
