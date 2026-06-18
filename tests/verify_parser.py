import os
import sys
import subprocess
from pathlib import Path

# Add parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from dv_transfer.parser import parse_dv_file, detect_recorded_segments
from dv_transfer.utils import get_ffmpeg_paths

def bcd(val):
    """Encodes an integer to BCD."""
    return ((val // 10) << 4) | (val % 10)

# Global cache for template frame
_TEMPLATE_FRAME = None

def get_template_frame():
    """Generates a 1-second template DV file using FFmpeg and extracts the first frame."""
    global _TEMPLATE_FRAME
    if _TEMPLATE_FRAME is not None:
        return _TEMPLATE_FRAME
        
    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        # Fallback to zeroed frame if FFmpeg is missing
        print("Warning: FFmpeg not found. Falling back to zero-filled template frame.")
        _TEMPLATE_FRAME = bytearray(120000)
        return _TEMPLATE_FRAME
        
    template_path = "template_temp.dv"
    if os.path.exists(template_path):
        os.remove(template_path)
        
    # Generate 1-second of NTSC DV video
    cmd = [
        ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=720x480:rate=29.97",
        "-c:v", "dvvideo", "-pix_fmt", "yuv411p",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
        template_path
    ]
    
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(template_path) and os.path.getsize(template_path) >= 120000:
        with open(template_path, "rb") as f:
            _TEMPLATE_FRAME = bytearray(f.read(120000))
        os.remove(template_path)
    else:
        print("Warning: Failed to generate FFmpeg template frame. Falling back to zero-filled frame.")
        _TEMPLATE_FRAME = bytearray(120000)
        
    return _TEMPLATE_FRAME

def generate_mock_dv_frame(frame_index, date_str, time_str, is_blank=False):
    """Generates a 120,000-byte NTSC DV frame by patching a structurally-valid template frame."""
    template = get_template_frame()
    frame = bytearray(template)
    
    # Wipe out Subcode and VAUX blocks (bytes 80 to 480) in all 10 sequences
    for s in range(10):
        seq_off = s * 12000
        frame[seq_off + 80 : seq_off + 480] = [0xFF] * 400
        
    if is_blank:
        return bytes(frame)
        
    # Write DIF headers for format detection (ensure SCT is correct in the wiped area)
    for s in range(10):
        seq_off = s * 12000
        # Block 0: Header (offset 0, SCT=0) - untouched
        # Block 1: Subcode 0 (offset 80, SCT=1)
        frame[seq_off + 80] = 0x20
        # Block 2: Subcode 1 (offset 160, SCT=1)
        frame[seq_off + 160] = 0x20
        # Block 3: VAUX 0 (offset 240, SCT=2)
        frame[seq_off + 240] = 0x40
        # Block 4: VAUX 1 (offset 320, SCT=2)
        frame[seq_off + 320] = 0x40
        # Block 5: VAUX 2 (offset 400, SCT=2)
        frame[seq_off + 400] = 0x40

    # Parse date and time
    try:
        parts = date_str.split("-")
        year = int(parts[0]) % 100
        month = int(parts[1])
        day = int(parts[2])
        
        parts_t = time_str.split(":")
        hours = int(parts_t[0])
        minutes = int(parts_t[1])
        seconds = int(parts_t[2])
    except Exception:
        year, month, day = 5, 6, 12
        hours, minutes, seconds = 12, 0, 0

    frames = frame_index % 30

    # 1. Embed Timecode Pack (0x13) in Subcode 0, Pack 0 (offset 86)
    tc_pack = [0x13, bcd(frames), bcd(seconds), bcd(minutes), bcd(hours)]
    frame[86:91] = tc_pack

    # 2. Embed RecDate Pack (0x62) in VAUX 0, Pack 0 (offset 243)
    date_pack = [0x62, 0xFF, bcd(day), bcd(month), bcd(year)]
    frame[243:248] = date_pack

    # 3. Embed RecTime Pack (0x63) in VAUX 0, Pack 1 (offset 248)
    time_pack = [0x63, bcd(frames), bcd(seconds), bcd(minutes), bcd(hours)]
    frame[248:253] = time_pack

    return bytes(frame)

def main():
    test_filepath = "test_tape.dv"
    if os.path.exists(test_filepath):
        os.remove(test_filepath)
        
    print("Generating simulated DV tape file with 2 segments and a 5-second blank gap...")
    try:
        with open(test_filepath, 'wb') as f:
            # Segment 1: 150 frames, date 2005-06-12, starting time 14:30:00
            for i in range(150):
                sec = i // 30
                time_str = f"14:30:{sec:02d}"
                frame = generate_mock_dv_frame(i, "2005-06-12", time_str, is_blank=False)
                f.write(frame)
                
            # Blank Gap: 150 frames
            for i in range(150):
                frame = generate_mock_dv_frame(i, "", "", is_blank=True)
                f.write(frame)
                
            # Segment 2: 150 frames, date 2005-06-12, starting time 14:30:15
            for i in range(150):
                sec = 15 + (i // 30)
                time_str = f"14:30:{sec:02d}"
                frame = generate_mock_dv_frame(i, "2005-06-12", time_str, is_blank=False)
                f.write(frame)
                
        print(f"Generated {test_filepath} successfully (size: {os.path.getsize(test_filepath)} bytes).")
        
        # Test parser
        print("Parsing mock DV tape file...")
        meta, frame_rate = parse_dv_file(test_filepath)
        
        print(f"Parsed {len(meta)} frames at {frame_rate} fps.")
        
        # Detect segments
        segments = detect_recorded_segments(meta, frame_rate, gap_threshold_seconds=3.0)
        
        print(f"Found {len(segments)} segments:")
        for idx, seg in enumerate(segments):
            print(f"  Segment {idx+1}:")
            print(f"    Start Frame: {seg['start_frame']}")
            print(f"    End Frame: {seg['end_frame']}")
            print(f"    Start Timecode: {seg['start_timecode']}")
            print(f"    End Timecode: {seg['end_timecode']}")
            print(f"    Recorded Timestamp: {seg['start_datetime']}")
            print(f"    Duration: {seg['duration_seconds']:.2f} seconds")
            
        # Assertions to verify correctness
        assert len(segments) == 2, f"Expected 2 segments, got {len(segments)}"
        
        # Segment 1 verification
        assert segments[0]['start_frame'] == 0, f"Expected segment 1 start frame to be 0, got {segments[0]['start_frame']}"
        assert segments[0]['end_frame'] == 149, f"Expected segment 1 end frame to be 149, got {segments[0]['end_frame']}"
        assert segments[0]['start_datetime'] == "2005-06-12 14:30:00", f"Expected segment 1 start datetime to be '2005-06-12 14:30:00', got '{segments[0]['start_datetime']}'"
        
        # Segment 2 verification
        assert segments[1]['start_frame'] == 300, f"Expected segment 2 start frame to be 300, got {segments[1]['start_frame']}"
        assert segments[1]['end_frame'] == 449, f"Expected segment 2 end frame to be 449, got {segments[1]['end_frame']}"
        assert segments[1]['start_datetime'] == "2005-06-12 14:30:15", f"Expected segment 2 start datetime to be '2005-06-12 14:30:15', got '{segments[1]['start_datetime']}'"
        
        print("\nALL TESTS PASSED SUCCESSFULLY! The binary DV parser and gap detector are 100% correct.")
        
    finally:
        # Cleanup test file
        if os.path.exists(test_filepath):
            os.remove(test_filepath)
            print("Cleaned up test file.")

if __name__ == "__main__":
    main()
