import argparse
import sys
import time
import os
import platform
import threading
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.live import Live
from rich.prompt import Prompt, Confirm
from rich.text import Text

from .utils import get_ffmpeg_paths, download_ffmpeg_windows, is_tool_executable
from .capture import list_capture_devices, run_capture
from .parser import parse_dv_file, detect_recorded_segments
from .transcoder import transcode_segment

console = Console()

def print_banner():
    banner_text = (
        "[bold cyan]██████╗ ██╗   ██╗    ████████╗██████╗  █████╗ ███╗   ██╗███████╗███████╗███████╗██████╗ \n"
        "██╔══██╗██║   ██║    ╚══██╔══╝██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝██╔══██╗\n"
        "██║  ██║██║   ██║       ██║   ██████╔╝███████║██╔██╗ ██║███████╗█████╗  █████╗  ██████╔╝\n"
        "██║  ██║╚██╗ ██╔╝       ██║   ██╔══██╗██╔══██║██║╚██╗██║╚════██║██╔══╝  ██╔══╝  ██╔══██╗\n"
        "██████╔╝ ╚████╔╝        ██║   ██║  ██║██║  ██║██║ ╚████║███████║██║     ███████╗██║  ██║\n"
        "╚═════╝   ╚═══╝         ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝     ╚══════╝╚═╝  ╚═╝[/bold cyan]\n"
        "           [bold white]IEEE 1394 FireWire Digital Video Capture & Split Engine[/bold white]"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))

def check_dependencies_and_prompt():
    """
    Checks for FFmpeg and FFprobe.
    If missing, prompts Windows users to download automatically.
    """
    ffmpeg_path, ffprobe_path = get_ffmpeg_paths()
    ffmpeg_ok = ffmpeg_path and is_tool_executable(ffmpeg_path)
    ffprobe_ok = ffprobe_path and is_tool_executable(ffprobe_path)
    
    if ffmpeg_ok and ffprobe_ok:
        return True
        
    console.print("\n[bold yellow]⚠️  Missing Dependencies Detected![/bold yellow]")
    console.print("This application requires [bold cyan]FFmpeg[/bold cyan] and [bold cyan]FFprobe[/bold cyan] to capture and transcode DV streams.")
    
    if platform.system() == "Windows":
        if Confirm.ask("Would you like to automatically download and install static Windows builds of FFmpeg now?"):
            run_ffmpeg_download()
            # Re-check
            ffmpeg_path, ffprobe_path = get_ffmpeg_paths()
            if ffmpeg_path and ffprobe_path:
                console.print("[bold green]✅ FFmpeg installed successfully![/bold green]")
                return True
            else:
                console.print("[bold red]❌ Installation verification failed. Please try installing FFmpeg manually.[/bold red]")
                return False
        else:
            console.print("[yellow]Please install FFmpeg manually and add it to your system PATH to run this application.[/yellow]")
            return False
    else:
        # macOS or Linux instructions
        if platform.system() == "Darwin":
            console.print("To install FFmpeg on macOS, you can use Homebrew:")
            console.print("  [bold green]brew install ffmpeg[/bold green]")
        else:
            console.print("To install FFmpeg on Linux, use your package manager:")
            console.print("  [bold green]sudo apt install ffmpeg dvgrab[/bold green]  (Debian/Ubuntu)")
            console.print("  [bold green]sudo dnf install ffmpeg dvgrab[/bold green]  (Fedora/CentOS)")
        return False

def run_ffmpeg_download():
    """Wrapper to run FFmpeg download with a beautiful rich progress bar."""
    with Progress(
        TextColumn("[bold blue]Downloading FFmpeg static archive..."),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn()
    ) as progress:
        task = progress.add_task("download", total=100)
        
        def update_progress(downloaded, total_size):
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                progress.update(task, completed=percent)
                
        try:
            download_ffmpeg_windows(progress_hook=update_progress)
            console.print("[bold green]Extracting binaries to workspace/bin/... Done![/bold green]")
        except Exception as e:
            console.print(f"[bold red]Error downloading FFmpeg: {e}[/bold red]")

def show_device_list():
    """Displays a clean table of all discovered video and audio capture devices."""
    with console.status("[bold cyan]Scanning for FireWire & capture devices..."):
        devices = list_capture_devices()
        
    table = Table(title="Available Capture Devices", border_style="cyan")
    table.add_column("Type", style="bold green", justify="center")
    table.add_column("Device Name / Index", style="white")
    
    for v in devices['video']:
        if isinstance(v, dict):
            table.add_row("Video", f"[{v['index']}] {v['name']}")
        else:
            table.add_row("Video", v)
            
    for a in devices['audio']:
        if isinstance(a, dict):
            table.add_row("Audio", f"[{a['index']}] {a['name']}")
        else:
            table.add_row("Audio", a)
            
    if not devices['video'] and not devices['audio']:
        console.print("[yellow]No capture devices found. Please verify your FireWire camcorder is turned on and connected.[/yellow]")
    else:
        console.print(table)

def handle_capture():
    """Guides the user through capturing a DV stream in real-time."""
    devices = list_capture_devices()
    video_device = None
    
    if devices['video']:
        choices = []
        for i, dev in enumerate(devices['video']):
            if isinstance(dev, dict):
                choices.append(str(dev['index']))
                console.print(f"[{i}] {dev['name']} (Index {dev['index']})")
            else:
                choices.append(str(i))
                console.print(f"[{i}] {dev}")
                
        choice = Prompt.ask("Select video capture device index", choices=choices + ["custom"], default="0")
        if choice == "custom":
            video_device = Prompt.ask("Enter custom video device name")
        else:
            idx = int(choice)
            video_device = devices['video'][idx]
            if isinstance(video_device, dict):
                video_device = video_device['name']
    else:
        console.print("[yellow]No video devices detected automatically.[/yellow]")
        video_device = Prompt.ask("Enter custom video device name (or press Enter for default)", default="")

    # Determine default captures directory and ensure it exists
    captures_dir = "./captures"
    Path(captures_dir).mkdir(parents=True, exist_ok=True)

    output_file = Prompt.ask("Enter output filename for raw DV capture", default="raw_tape.dv")
    if not output_file.endswith(".dv"):
        output_file += ".dv"
        
    # If the user just typed a filename (no directory path), default to captures directory
    if not os.path.dirname(output_file):
        output_file = os.path.join(captures_dir, output_file)
    else:
        # Ensure parent directory of custom path exists
        parent_dir = os.path.dirname(output_file)
        if parent_dir:
            Path(parent_dir).mkdir(parents=True, exist_ok=True)
        
    auto_stop_timeout_str = Prompt.ask(
        "Enter tape-end auto-stop timeout in seconds (0 to disable, e.g., 10)",
        default="0"
    )
    try:
        auto_stop_timeout = int(auto_stop_timeout_str)
    except ValueError:
        auto_stop_timeout = 0
        
    console.print("\n[bold yellow]Preparing Capture...[/bold yellow]")
    console.print("1. Set your DV Camcorder to [bold green]VTR / PLAYBACK[/bold green] mode.")
    console.print("2. Rewind the tape to the start (or where you want to begin).")
    console.print("3. Press [bold cyan]PLAY[/bold cyan] on the camcorder deck.")
    
    if not Confirm.ask("Ready to start recording?"):
        return
        
    stop_event = threading.Event()
    
    # Thread tracking state
    capture_data = {'elapsed': 0.0, 'size': 0, 'auto_stopped': False, 'error': None}
    
    def status_cb(elapsed, size):
        capture_data['elapsed'] = elapsed
        capture_data['size'] = size
        
    def capture_worker():
        try:
            auto_stop = run_capture(
                video_device_name=video_device,
                output_filepath=output_file,
                status_callback=status_cb,
                stop_event=stop_event,
                auto_stop_timeout=auto_stop_timeout
            )
            capture_data['auto_stopped'] = auto_stop
        except Exception as e:
            capture_data['error'] = e

    t = threading.Thread(target=capture_worker, daemon=True)
    t.start()
    
    console.print("\n[bold green]🔴 Capture Session Active[/bold green]")
    console.print("Monitoring stream... Press [bold yellow]Ctrl+C[/bold yellow] to stop capture manually.\n")
    
    # Live dashboard updates in place
    try:
        with Live(console=console, auto_refresh=True) as live:
            while t.is_alive():
                time.sleep(0.5)
                size_mb = capture_data['size'] / (1024 * 1024)
                elapsed_str = time.strftime('%H:%M:%S', time.gmtime(capture_data['elapsed']))
                
                auto_stop_status = f"Active ({auto_stop_timeout}s inactivity)" if auto_stop_timeout > 0 else "Disabled (Capture through gaps)"
                dashboard = (
                    f"⏱️  [bold white]Elapsed time:[/bold white] {elapsed_str}\n"
                    f"📦  [bold white]Raw file size:[/bold white] {size_mb:.2f} MB\n"
                    f"💾  [bold white]Output destination:[/bold white] {output_file}\n"
                    f"🤖  [bold white]Tape End Auto-Stop:[/bold white] [green]{auto_stop_status}[/green]"
                )
                live.update(Panel(dashboard, title="Live Capture Status", border_style="red", expand=False))
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping capture cleanly (sending quit signal to FFmpeg)...[/yellow]")
        stop_event.set()
        
    t.join()
    
    if capture_data['error']:
        console.print(f"[bold red]Capture failed with error: {capture_data['error']}[/bold red]")
    else:
        size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
        if capture_data['auto_stopped']:
            console.print(f"\n[bold green]🎉 Tape end detected! Capture stopped automatically.[/bold green]")
        else:
            console.print(f"\n[bold green]✅ Capture stopped successfully.[/bold green]")
        console.print(f"Final size: [bold white]{size_mb:.2f} MB[/bold white] saved to [cyan]{output_file}[/cyan].\n")

def handle_parse_and_split(input_file=None, output_dir=None, gap_threshold=3.0, unattended=False, profile=None):
    """Parses a raw DV file and transcodes segments into MP4 or MKV files."""
    if not input_file:
        # Scan for .dv files in ./captures and the current directory
        dv_files = []
        
        # Scan ./captures if it exists
        captures_dir = "./captures"
        if os.path.exists(captures_dir):
            try:
                for f in os.listdir(captures_dir):
                    if f.endswith(".dv"):
                        dv_files.append(os.path.join(captures_dir, f))
            except Exception:
                pass
                    
        # Scan current working directory
        try:
            for f in os.listdir("."):
                if f.endswith(".dv"):
                    full_path = os.path.join(".", f)
                    full_path_norm = os.path.normpath(full_path)
                    if not any(os.path.normpath(x) == full_path_norm for x in dv_files):
                        dv_files.append(full_path)
        except Exception:
            pass
                    
        if dv_files:
            console.print("\n[bold cyan]Discovered raw DV capture files:[/bold cyan]")
            for idx, filepath in enumerate(dv_files):
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                console.print(f"[{idx}] {filepath} ({size_mb:.2f} MB)")
            console.print(f"[{len(dv_files)}] Enter custom path manually")
            
            choices = [str(x) for x in range(len(dv_files) + 1)]
            choice = Prompt.ask("Select a file to parse", choices=choices, default="0")
            
            if int(choice) < len(dv_files):
                input_file = dv_files[int(choice)]
            else:
                input_file = Prompt.ask("Enter custom path to raw DV file")
        else:
            input_file = Prompt.ask("Enter path to raw DV file to parse")
    if not os.path.exists(input_file):
        console.print(f"[bold red]File not found: {input_file}[/bold red]")
        return
        
    if not output_dir:
        output_dir = Prompt.ask("Enter directory to save output clips", default="./clips")
        
    # Get profile selection
    if not profile:
        if unattended:
            profile = "delivery"
        else:
            console.print("\n[bold cyan]Select Output Format Profile:[/bold cyan]")
            console.print("[1] H.264 / AAC MP4 (Compatible Delivery Format - Recommended)")
            console.print("[2] FFV1 / FLAC MKV (Lossless Archive Format)")
            choice = Prompt.ask("Choose profile", choices=["1", "2"], default="1")
            profile = "delivery" if choice == "1" else "archive"
            
    # Extract the input file base name (no directory, no extension)
    input_base = os.path.basename(input_file)
    input_name, _ = os.path.splitext(input_base)
    
    # Construct a dedicated subdirectory for the clips
    final_output_dir = os.path.join(output_dir, input_name)
    Path(final_output_dir).mkdir(parents=True, exist_ok=True)
    
    # Parse DV file
    console.print(f"\n[bold cyan]Analyzing {os.path.basename(input_file)} for tape metadata...[/bold cyan]")
    
    metadata = []
    fps = 29.97
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn()
    ) as progress:
        task = progress.add_task("Parsing DV frames...", total=100)
        
        def parse_cb(current, total):
            if total > 0:
                progress.update(task, completed=(current / total) * 100)
                
        try:
            metadata, fps = parse_dv_file(input_file, progress_callback=parse_cb)
        except Exception as e:
            console.print(f"[bold red]Failed to parse DV file: {e}[/bold red]")
            return
 
    console.print(f"[bold green]Analysis complete. Total frames parsed: {len(metadata)} ({format(len(metadata)/fps, '.2f')}s at {fps} fps).[/bold green]")
    
    # Detect segments
    segments = detect_recorded_segments(metadata, fps, gap_threshold_seconds=gap_threshold)
    
    if not segments:
        console.print("[yellow]No recorded video segments found in this file. It appears to be entirely blank tape.[/yellow]")
        return
        
    # Show segments table
    table = Table(title="Detected Video Sequences (Separated by Tape Gaps)", border_style="cyan")
    table.add_column("Seq #", justify="center")
    table.add_column("Start Timecode", style="green")
    table.add_column("End Timecode", style="green")
    table.add_column("Recorded Timestamp", style="white")
    table.add_column("Duration (H:M:S)", justify="right")
    
    for idx, seg in enumerate(segments):
        duration_str = time.strftime('%H:%M:%S', time.gmtime(seg['duration_seconds']))
        table.add_row(
            str(idx + 1),
            seg['start_timecode'] or "00:00:00:00",
            seg['end_timecode'] or "00:00:00:00",
            seg['start_datetime'] or "Unknown Date/Time",
            duration_str
        )
    console.print(table)
    
    if not unattended:
        if not Confirm.ask(f"Do you want to transcode these {len(segments)} sequences to compatible MP4/MKV format now?"):
            return
        
    # Transcode segments
    trans_desc = "Transcoding Sequences to MP4 (H.264 / AAC)..." if profile == "delivery" else "Transcoding Sequences to MKV (FFV1 / FLAC)..."
    console.print(f"\n[bold cyan]{trans_desc}[/bold cyan]")
    
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        overall_task = progress.add_task("[bold green]Overall Progress:", total=len(segments))
        
        ext = ".mkv" if profile == "archive" else ".mp4"
        
        for idx, seg in enumerate(segments):
            # Compute file name based on recording date/time or index
            if seg['start_datetime'] and "Unknown" not in seg['start_datetime']:
                # Format date code to file-safe string: YYYY-MM-DD_HH-MM-SS
                datetime_str = seg['start_datetime'].replace(" ", "_").replace(":", "-")
                filename = f"clip_{datetime_str}{ext}"
            else:
                filename = f"clip_sequence_{idx+1:03d}{ext}"
                
            output_filepath = os.path.join(final_output_dir, filename)
            
            # Start/End seconds
            start_sec = seg['start_frame'] / fps
            end_sec = (seg['end_frame'] + 1) / fps
            
            # Define individual clip task description
            clip_desc = f"[cyan]Encoding Clip {idx+1}/{len(segments)} -> {filename}[/cyan]"
            clip_task = progress.add_task(clip_desc, total=100)
            
            def trans_cb(percent):
                progress.update(clip_task, completed=percent * 100)
                
            try:
                transcode_segment(
                    input_filepath=input_file,
                    output_filepath=output_filepath,
                    start_seconds=start_sec,
                    end_seconds=end_sec,
                    creation_time=seg['start_datetime'],
                    progress_callback=trans_cb,
                    profile=profile
                )
            except Exception as e:
                console.print(f"[bold red]❌ Failed to transcode clip {idx+1}: {e}[/bold red]")
            finally:
                progress.remove_task(clip_task)
                progress.update(overall_task, advance=1)
                
    console.print(f"\n[bold green]🎉 Success! All clips transcoded and saved in {final_output_dir}.[/bold green]\n")

def run_interactive_tui():
    """Launches the interactive TUI menu loop."""
    print_banner()
    
    # Check dependencies on startup
    if not check_dependencies_and_prompt():
        console.print("[yellow]Note: Some CLI features (like parser testing) are still active, but capture/transcoding is unavailable without FFmpeg.[/yellow]")
        
    while True:
        console.print("\n[bold cyan]--- MAIN MENU ---[/bold cyan]")
        console.print("[1] Scan and List Capture Devices")
        console.print("[2] Capture Video from DV Camcorder over FireWire")
        console.print("[3] Analyze and Split DV Video File by Gaps")
        console.print("[4] Download/Re-install FFmpeg (Windows only)")
        console.print("[5] Exit")
        
        choice = Prompt.ask("Choose an action", choices=["1", "2", "3", "4", "5"], default="3")
        
        if choice == "1":
            show_device_list()
        elif choice == "2":
            # Require FFmpeg verification
            ffmpeg_path, _ = get_ffmpeg_paths()
            if not ffmpeg_path or not is_tool_executable(ffmpeg_path):
                console.print("[bold red]Capture requires FFmpeg installed and working. Please download FFmpeg first.[/bold red]")
                continue
            handle_capture()
        elif choice == "3":
            # Require FFmpeg verification
            ffmpeg_path, _ = get_ffmpeg_paths()
            if not ffmpeg_path or not is_tool_executable(ffmpeg_path):
                console.print("[bold red]Splitting/Transcoding requires FFmpeg. Please download FFmpeg first.[/bold red]")
                continue
            handle_parse_and_split()
        elif choice == "4":
            if platform.system() != "Windows":
                console.print("[yellow]Automatic FFmpeg download is only available on Windows. For other OS platforms, use brew or apt.[/yellow]")
            else:
                run_ffmpeg_download()
        elif choice == "5":
            console.print("[cyan]Goodbye![/cyan]")
            break

def main():
    """Main CLI entry point parses arguments or runs interactive menu."""
    parser = argparse.ArgumentParser(description="Cross-platform DV FireWire capture and gap splitting tool.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch the interactive terminal TUI.")
    parser.add_argument("--list-devices", "-l", action="store_true", help="Lists discovered video and audio capture devices.")
    parser.add_argument("--input", "-in", type=str, help="Path to raw DV file to process/split.")
    parser.add_argument("--output-dir", "-out", type=str, default="./clips", help="Output directory for MP4/MKV clips.")
    parser.add_argument("--gap-threshold", "-gap", type=float, default=3.0, help="Gaps longer than this (seconds) trigger clip splits.")
    parser.add_argument("--auto-stop-timeout", "-ast", type=int, default=0, help="Tape-end auto-stop inactivity timeout in seconds (0 to disable).")
    parser.add_argument("--profile", "-prof", type=str, choices=["delivery", "archive"], default="delivery", help="Output format profile: delivery (H.264/AAC MP4) or archive (FFV1/FLAC MKV)")
    
    args = parser.parse_args()
    
    # Default to interactive if no specific action argument is given
    if args.interactive or (len(sys.argv) == 1):
        run_interactive_tui()
    elif args.list_devices:
        show_device_list()
    elif args.input:
        handle_parse_and_split(
            input_file=args.input,
            output_dir=args.output_dir,
            gap_threshold=args.gap_threshold,
            unattended=True,
            profile=args.profile
        )
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
