import os
import sys
import platform
import subprocess
import time
import threading
import shutil
from pathlib import Path
from .utils import get_ffmpeg_paths

def list_capture_devices():
    """
    Lists available video and audio capture devices.
    Returns a dict with lists: {'video': [...], 'audio': [...]}
    Each device is represented as a string or dict.
    """
    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        return {'video': [], 'audio': []}

    system = platform.system()
    video_devices = []
    audio_devices = []

    if system == "Windows":
        # Run ffmpeg to list DirectShow devices
        cmd = [ffmpeg_path, "-f", "dshow", "-list_devices", "true", "-i", "dummy"]
        # FFmpeg outputs device list to stderr, and exits with code 1 (since dummy input fails)
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        
        current_section = None
        for line in res.stderr.splitlines():
            line = line.strip()
            if "DirectShow video devices" in line:
                current_section = "video"
                continue
            elif "DirectShow audio devices" in line:
                current_section = "audio"
                continue
            
            # Match lines with device name, like [dshow @ 0000...]  "Microsoft DV Camera and VCR"
            if current_section and '"' in line and "Alternative name" not in line:
                start_idx = line.find('"')
                end_idx = line.rfind('"')
                if start_idx != -1 and end_idx != -1 and start_idx != end_idx:
                    dev_name = line[start_idx+1:end_idx]
                    if current_section == "video":
                        video_devices.append(dev_name)
                    else:
                        audio_devices.append(dev_name)

    elif system == "Darwin":  # macOS
        cmd = [ffmpeg_path, "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        
        current_section = None
        for line in res.stderr.splitlines():
            line = line.strip()
            if "AVFoundation video devices" in line:
                current_section = "video"
                continue
            elif "AVFoundation audio devices" in line:
                current_section = "audio"
                continue
                
            # Match lines with index, like [AVFoundation ...] [0] FaceTime HD Camera
            if current_section and "]" in line:
                parts = line.split("]")
                if len(parts) >= 2:
                    # Find the index and name
                    last_part = parts[-1].strip()
                    # Example layout: "[0] FaceTime HD Camera"
                    # parts[-2] will have "[0", parts[-1] will be " FaceTime HD Camera"
                    index_part = parts[-2].split("[")[-1].strip()
                    if index_part.isdigit():
                        dev_info = {'index': int(index_part), 'name': last_part}
                        if current_section == "video":
                            video_devices.append(dev_info)
                        else:
                            audio_devices.append(dev_info)

    elif system == "Linux":
        # On Linux, dvgrab is preferred. We check if there are 1394 ports or v4l2
        # For simplicity, we check v4l2 devices via sysfs
        v4l_dir = Path("/sys/class/video4linux")
        if v4l_dir.exists():
            for dev_path in v4l_dir.iterdir():
                name_file = dev_path / "name"
                if name_file.is_file():
                    with open(name_file, 'r') as f:
                        dev_name = f.read().strip()
                    video_devices.append(f"/dev/{dev_path.name} ({dev_name})")
                    
        # Check raw1394 or ieee1394 devices
        if os.path.exists("/dev/raw1394") or any(p.name.startswith("fw") for p in Path("/dev").glob("fw*")):
            video_devices.append("IEEE1394 FireWire Device (Auto-detect via dvgrab)")

    return {'video': video_devices, 'audio': audio_devices}

def run_capture(video_device_name, output_filepath, status_callback=None, stop_event=None, auto_stop_timeout=0):
    """
    Runs the capture process using FFmpeg (or dvgrab on Linux) in a subprocess.
    Monitors file size growth and handles automatic stopping if it stalls.
    status_callback is a callable: status_callback(elapsed_seconds, file_size_bytes)
    stop_event is a threading.Event used to signal manual stop.
    auto_stop_timeout is the inactivity period (in seconds) to trigger auto-stop. Set to 0 to disable.
    """
    ffmpeg_path, _ = get_ffmpeg_paths()
    system = platform.system()
    
    # Construct capture command
    cmd = []
    
    if system == "Windows":
        if not ffmpeg_path:
            raise FileNotFoundError("FFmpeg is required for capture on Windows.")
        # If no specific device is chosen, try standard MS DV Camera
        device = video_device_name if video_device_name else "Microsoft DV Camera and VCR"
        # Using DirectShow. We set -c copy to copy the raw DV payload
        cmd = [
            ffmpeg_path, "-y",
            "-f", "dshow",
            "-i", f"video={device}",
            "-c", "copy",
            output_filepath
        ]
    elif system == "Darwin":  # macOS
        if not ffmpeg_path:
            raise FileNotFoundError("FFmpeg is required for capture on macOS.")
        # macOS uses AVFoundation index
        device = "0"
        if isinstance(video_device_name, dict) and 'index' in video_device_name:
            device = str(video_device_name['index'])
        elif isinstance(video_device_name, str) and video_device_name.isdigit():
            device = video_device_name
            
        cmd = [
            ffmpeg_path, "-y",
            "-f", "avfoundation",
            "-i", device,
            "-c:v", "copy", "-c:a", "copy",  # copy raw DV frames if possible
            output_filepath
        ]
    elif system == "Linux":
        # Check if dvgrab is installed
        dvgrab_path = shutil.which("dvgrab")
        if dvgrab_path:
            # dvgrab writes raw DV to file
            cmd = [dvgrab_path, "-size", "0", "-format", "raw", "-single", output_filepath]
        elif ffmpeg_path:
            # Fallback to ffmpeg V4L2 capture
            device = video_device_name if video_device_name else "/dev/video0"
            cmd = [
                ffmpeg_path, "-y",
                "-f", "v4l2",
                "-i", device,
                "-c", "copy",
                output_filepath
            ]
        else:
            raise FileNotFoundError("Neither dvgrab nor FFmpeg was found. Please install dvgrab or FFmpeg.")

    # Start the process
    # We pipe stdin so we can send the 'q' key to stop FFmpeg cleanly
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0
    )
    
    start_time = time.time()
    last_size = 0
    last_size_time = time.time()
    auto_stop_triggered = False
    
    # Ensure file exists or wait for it to be created
    time.sleep(1)
    
    while process.poll() is None:
        # Check if stop event is set by CLI thread (manual stop)
        if stop_event and stop_event.is_set():
            # Stop FFmpeg cleanly by writing 'q'
            try:
                process.stdin.write('q\n')
                process.stdin.flush()
            except Exception:
                pass
            
            # Wait for it to close, force kill if needed after 3 seconds
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            break
            
        # Check file size of output
        elapsed = time.time() - start_time
        file_size = 0
        if os.path.exists(output_filepath):
            file_size = os.path.getsize(output_filepath)
            
        if file_size > last_size:
            last_size = file_size
            last_size_time = time.time()
        else:
            # File size did not increase. If it has been more than auto_stop_timeout, auto stop
            if auto_stop_timeout > 0 and time.time() - last_size_time > auto_stop_timeout and elapsed > 5.0:
                auto_stop_triggered = True
                try:
                    process.stdin.write('q\n')
                    process.stdin.flush()
                except Exception:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
                
        if status_callback:
            status_callback(elapsed, file_size)
            
        time.sleep(0.5)
        
    # Final check on return code
    stdout, stderr = process.communicate()
    exit_code = process.returncode
    
    # If the process failed and we didn't trigger an autostop or manual stop, raise error
    if exit_code != 0 and not auto_stop_triggered and not (stop_event and stop_event.is_set()):
        # Exclude dvgrab single capture normal exits
        if system == "Linux" and "dvgrab" in cmd[0] and os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 0:
            pass
        else:
            raise RuntimeError(f"Capture process failed with code {exit_code}.\nError details:\n{stderr}")
            
    return auto_stop_triggered
