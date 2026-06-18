# 📼 DV-Transfer Engine

A cross-platform command-line tool (CLI) and interactive Terminal User Interface (TUI) to transfer raw Digital Video (DV) tapes over FireWire (IEEE 1394) and split the content into separate, compressed, and widely supported MP4 files.

The program automatically detects unrecorded "blank tape" gaps (where timecode/recording metadata is missing), skips them, and groups continuous recordings into distinct `.mp4` video files encoded in H.264 video and AAC audio.

---

## ✨ Features

- **🔴 FireWire Capture:** Capture raw DV streams in real-time from connected camcorders using DirectShow (Windows), AVFoundation (macOS), or `dvgrab`/raw1394 (Linux).
- **🤖 Tape-End Auto-Stop:** Monitors the active file size during capture and automatically stops recording if the tape reaches its end or stops playing for 5 seconds.
- **🔍 Low-Level DV Binary Parsing:** Scans raw `.dv` streams frame-by-frame, decoding BCD timecode (`0x13`), recording date (`0x62`), and recording time (`0x63`) packs to find shot cuts and gaps. Gaps are filtered using majority voting to remain resilient to signal noise and bit-errors.
- **🎬 Smart Gap Splitting:** Automatically strings together continuous clips and splits out recordings separated by blank spaces (default threshold is 3 seconds, customizable with `--gap-threshold`).
- **⚙️ Automated FFmpeg Downloader:** Checks for FFmpeg and FFprobe on startup. If missing on Windows, it prompts the user and automatically downloads and extracts the official static release builds.
- **📱 Premium MP4 Transcoding:** Transcodes raw DV (which is massive and widely unsupported) to highly compatible H.264 video and AAC audio, injecting the original recording date into the output metadata so indexers (like Apple Photos, Google Photos, Plex) show the correct date.

---

## 🚀 Installation & Requirements

1. **Python 3.10+** is required.
2. **Setup Virtual Environment (Recommended):**
   Create and activate a virtual environment to isolate package dependencies:
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux:**
     ```bash
     python -m venv .venv
     source .venv/bin/activate
     ```
3. Install package dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. **FFmpeg & FFprobe:**
   - **Windows:** The application will offer to download FFmpeg automatically on startup.
   - **macOS:** Install via Homebrew: `brew install ffmpeg`
   - **Linux:** Install via package manager: `sudo apt install ffmpeg dvgrab` (Linux uses `dvgrab` for native IEEE 1394 hardware deck control).

---

## 💻 Usage

Run the program from the repository root:

### 1. Interactive Menu (TUI)
Simply run without arguments to launch the colorful interactive menu:
```bash
python main.py
```
This launches the step-by-step TUI dashboard which will guide you through listing connected devices, capturing tape video, and processing/splitting existing `.dv` files.

### 2. Command Line Scripting (CLI Flags)
For automated scripting, you can pass command-line arguments:

#### Analyze and Split an Existing DV File:
```bash
python main.py --input raw_tape.dv --output-dir ./my_clips --gap-threshold 5.0
```

#### List Discovered Capture Devices:
```bash
python main.py --list-devices
```

---

## 🛠️ Project Structure

- **`main.py`**: Repository root entrypoint script.
- **`dv_transfer/`**: Core source directory:
  - `cli.py`: Terminal UI implementation and command line parsing.
  - `capture.py`: Scans devices and manages live capture subprocesses.
  - `parser.py`: Auto-detects formats (NTSC vs PAL) and parses binary subcode packs.
  - `transcoder.py`: Cuts raw segments and transcodes to H.264/AAC.
  - `utils.py`: Checks dependencies and handles automated downloads.
- **`tests/`**: Automated verification test suites:
  - `verify_parser.py`: Creates a mock DV file to verify parser BCD decoding.
  - `verify_integration.py`: End-to-end simulation test (runs the CLI flags on generated DV streams and validates output MP4 files).

---

## 🔬 Under the Hood: DV DIF Binary Parsing

Raw DV streams (`.dv` files) consist of fixed-size frames (NTSC frames are exactly 120,000 bytes; PAL frames are 144,000 bytes). Each frame contains 12,000-byte DIF sequences.

`dv-transfer` parses these sequences at the byte-level:
- **Timecode (`0x13`)** is read from the **Subcode block** payloads (occurring at byte offsets `86 + j * 8` and `166 + j * 8` relative to each sequence start).
- **Recording Date (`0x62`)** and **Recording Time (`0x63`)** are read from **VAUX block** payloads (occurring at offsets `243 + p * 5`, `323 + p * 5`, and `403 + p * 5`).

The parsed bytes are unpacked using Binary Coded Decimal (BCD) masking to reconstruct dates and times. If a sequence of frames does not contain valid metadata packs, the segment is classified as a gap.
