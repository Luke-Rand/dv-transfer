import os
import subprocess
import platform
import time
from .utils import get_ffmpeg_paths

def transcode_segment(input_filepath, output_filepath, start_seconds, end_seconds, creation_time=None, progress_callback=None):
    """
    Transcodes a segment of a raw DV file into an MP4 file.
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
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
    ]

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
            # Wait for the process to finish
            process.wait()
            exit_code = process.returncode
            
        if exit_code != 0:
            stderr_file.seek(0)
            stderr = stderr_file.read()
            raise RuntimeError(f"Transcoding failed with exit code {exit_code}.\nError details:\n{stderr}")
