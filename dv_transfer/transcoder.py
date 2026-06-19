import os
import subprocess
import platform
import time
import threading
from .utils import get_ffmpeg_paths

# Thread-safe registry to track active FFmpeg transcoding subprocesses
_active_processes = set()
_active_processes_lock = threading.Lock()

def register_process(proc):
    with _active_processes_lock:
        _active_processes.add(proc)

def unregister_process(proc):
    with _active_processes_lock:
        _active_processes.discard(proc)

def kill_active_processes():
    """Terminates all registered transcoding subprocesses immediately."""
    with _active_processes_lock:
        for proc in list(_active_processes):
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _active_processes.clear()

def transcode_segment(input_filepath, output_filepath, start_seconds, end_seconds, creation_time=None, progress_callback=None, profile="delivery"):
    """
    Transcodes a segment of a raw DV file into an MP4/MKV file.
    Optionally sets the creation_time metadata.
    progress_callback is a callable: progress_callback(percentage_float)
    """
    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        raise FileNotFoundError("FFmpeg is required for transcoding.")

    duration_seconds = end_seconds - start_seconds
    if duration_seconds <= 0:
        raise ValueError("Segment duration must be positive.")

    # Build command
    cmd = [
        ffmpeg_path, "-y",
        "-ss", f"{start_seconds:.3f}",
        "-to", f"{end_seconds:.3f}",
        "-i", input_filepath,
        "-vf", "yadif",
    ]

    if profile == "archive":
        cmd.extend([
            "-c:v", "ffv1",
            "-level", "3",
            "-coder", "1",
            "-context", "1",
            "-g", "1",
            "-c:a", "flac"
        ])
    else:
        # Default to delivery (H.264/AAC)
        cmd.extend([
            "-c:v", "libx264",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
        ])

    if creation_time:
        # Format creation_time: "YYYY-MM-DD HH:MM:SS" -> ISO "YYYY-MM-DDTHH:MM:SS"
        iso_time = creation_time.replace(" ", "T")
        cmd.extend(["-metadata", f"creation_time={iso_time}"])

    # Redirect progress report to stdout
    cmd.extend(["-progress", "-", output_filepath])

    import tempfile

    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stderr_file:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=0
        )
        register_process(process)

        try:
            # Read lines from progress output
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                    
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        time_us = int(line.split("=")[1])
                        elapsed_seconds = time_us / 1_000_000.0
                        percent = min(1.0, elapsed_seconds / duration_seconds)
                        if progress_callback:
                            progress_callback(percent)
                    except ValueError:
                        pass
                elif line.startswith("progress=end"):
                    if progress_callback:
                        progress_callback(1.0)
        finally:
            unregister_process(process)
            # Wait for the process to finish
            process.wait()
            exit_code = process.returncode
            
        if exit_code != 0:
            # Cleanup incomplete files on error/cancellation
            if os.path.exists(output_filepath):
                try:
                    os.remove(output_filepath)
                except Exception:
                    pass
            stderr_file.seek(0)
            stderr = stderr_file.read()
            raise RuntimeError(f"Transcoding failed with exit code {exit_code}.\nError details:\n{stderr}")
