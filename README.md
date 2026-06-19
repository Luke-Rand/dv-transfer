# DV-Transfer

A cross-platform Python CLI/TUI application to capture raw Digital Video (DV) streams from camcorders over FireWire (IEEE 1394), automatically detect blank tape gaps and timecode discontinuities, and split the tape capture into individual progressive MP4 (H.264/AAC) or MKV (FFV1/FLAC) files.

The program parses raw DV frames, decodes embedded subcode metadata, and splits the stream at shot boundaries (timecode jumps) or unrecorded tape gaps.

---

## Features

- **FireWire Capture**: Live capture of raw DV streams from connected camcorders using DirectShow (Windows), AVFoundation (macOS), or `dvgrab` (Linux).
- **Inactivity Detection (Auto-Stop)**: Optional monitoring of raw capture file growth to automatically stop recording when the tape ends or stops playing.
- **Low-Level DV Parsing**: Binary parsing of raw `.dv` streams at the frame level to decode BCD timecodes, recording dates, and recording times from Subcode and VAUX areas. Majority voting is used to remain resilient to signal noise and bit errors.
- **Discontinuity & Gap Splitting**: Automatic splitting of video files based on timecode jumps (e.g. paused/resumed recordings) and missing metadata gaps, with lookahead smoothing to prevent false splits on transient signal dropouts.
- **Parallel Transcoding**: Multi-threaded transcoding of tape segments using a subprocess-based thread pool to speed up processing on multi-core systems.
- **Transcoding Profiles**:
  - **Delivery**: Progressive H.264/AAC in an MP4 container (using `yadif` deinterlacing).
  - **Lossless Archive**: Progressive FFV1/FLAC in an MKV container (using `yadif` deinterlacing).
- **FFmpeg Auto-Downloader**: Automatically downloads and extracts local static builds of FFmpeg/FFprobe on Windows if they are not present in the system PATH.

---

## Installation & Requirements

1. **Python 3.10+** is required.
2. **Setup Virtual Environment:**
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
   - **Windows**: The application will offer to download FFmpeg automatically on startup.
   - **macOS**: Install via Homebrew: `brew install ffmpeg`
   - **Linux**: Install via package manager: `sudo apt install ffmpeg dvgrab` (Linux uses `dvgrab` for native IEEE 1394 hardware deck control).

---

## Usage

Run the program from the repository root:

### 1. Interactive Menu (TUI)
Run without arguments to launch the interactive terminal menu:
```bash
python main.py
```
This launches a step-by-step TUI dashboard to scan capture devices, capture raw video (saved in the `./captures/` folder), and parse or split raw tape files.

### 2. Command Line Scripting (CLI Flags)
For automated scripting, you can pass command-line arguments:

#### Analyze and Split an Existing DV File:
```bash
python main.py --input captures/raw_tape.dv --output-dir ./my_clips --profile archive --gap-threshold 2.0
```

#### List Discovered Capture Devices:
```bash
python main.py --list-devices
```

#### CLI Flags:
* `--interactive`, `-i`: Launch the interactive terminal TUI menu.
* `--list-devices`, `-l`: Lists discovered video and audio capture devices.
* `--input`, `-in`: Path to raw DV file to process/split.
* `--output-dir`, `-out`: Output directory for MP4/MKV clips (defaults to `./clips`).
* `--gap-threshold`, `-gap`: Gap threshold in seconds (defaults to `3.0`). Timecode gaps longer than this trigger splits.
* `--auto-stop-timeout`, `-ast`: Tape-end auto-stop inactivity timeout in seconds (defaults to `0`/disabled).
* `--profile`, `-prof`: Output format profile: `delivery` (H.264/AAC MP4) or `archive` (FFV1/FLAC MKV) (defaults to `delivery`).

---

## Project Structure

- **`main.py`**: Entrypoint script at the repository root.
- **`dv_transfer/`**: Core package directory:
  - `cli.py`: Terminal UI implementation, menus, and command-line parsing.
  - `capture.py`: Discovery of devices and live capture monitoring.
  - `parser.py`: Format auto-detection (NTSC vs PAL) and subcode binary parsing.
  - `transcoder.py`: Slices and transcodes raw segments to MP4/MKV.
  - `utils.py`: FFmpeg validation and automated Windows download helper.
- **`tests/`**: Automated verification test suites:
  - `verify_parser.py`: Simulates raw DV frames and verifies parser BCD decoding.
  - `verify_integration.py`: End-to-end integration test validating the TUI CLI flags on mock streams under both profiles.

---

## Under the Hood: DV DIF Binary Parsing

Raw DV streams consist of fixed-size frames (NTSC frames are exactly 120,000 bytes; PAL frames are 144,000 bytes). Each frame contains 12,000-byte DIF sequences.

`dv-transfer` parses these sequences at the byte level:
- **Timecode (`0x13`)** is read from the **Subcode block** payloads (occurring at byte offsets `86 + j * 8` and `166 + j * 8` relative to each sequence start).
- **Recording Date (`0x62`)** and **Recording Time (`0x63`)** are read from **VAUX block** payloads (occurring at offsets `243 + p * 5`, `323 + p * 5`, and `403 + p * 5`).

The parsed bytes are unpacked using Binary Coded Decimal (BCD) masking to reconstruct dates and times. If a sequence of frames has discontinuous or missing timecode packets, the segment is split.
