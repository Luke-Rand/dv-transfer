import os
import sys
import subprocess
import shutil
from pathlib import Path

# Add parent directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from tests.verify_parser import generate_mock_dv_frame

def main():
    test_filepath = "test_tape_integration.dv"
    output_dir = "./test_clips"
    
    # Clean up any previous runs
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        
    print("Generating simulated DV tape file for integration testing...")
    try:
        with open(test_filepath, 'wb') as f:
            # Segment 1: 90 frames (3 seconds), date 2005-06-12, starting time 14:30:00
            for i in range(90):
                sec = i // 30
                time_str = f"14:30:{sec:02d}"
                frame = generate_mock_dv_frame(i, "2005-06-12", time_str, is_blank=False)
                f.write(frame)
                
            # Blank Gap: 120 frames (4 seconds), completely empty bytes
            for i in range(120):
                frame = generate_mock_dv_frame(i, "", "", is_blank=True)
                f.write(frame)
                
            # Segment 2: 90 frames (3 seconds), date 2005-06-12, starting time 14:30:15
            for i in range(90):
                sec = 15 + (i // 30)
                time_str = f"14:30:{sec:02d}"
                frame = generate_mock_dv_frame(i, "2005-06-12", time_str, is_blank=False)
                f.write(frame)
                
        print(f"Generated {test_filepath} (size: {os.path.getsize(test_filepath)} bytes).")
        
        # --- TEST CASE 1: Delivery Profile (H.264/AAC MP4) ---
        print("\n--- Running Test Case 1: Delivery Profile (H.264/AAC MP4) ---")
        cmd_delivery = [
            sys.executable, "-m", "dv_transfer",
            "--input", test_filepath,
            "--output-dir", output_dir,
            "--gap-threshold", "3.0",
            "--profile", "delivery"
        ]
        
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        res_delivery = subprocess.run(cmd_delivery, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        
        print("\n--- CLI STDOUT (Delivery) ---")
        try:
            print(res_delivery.stdout)
        except UnicodeEncodeError:
            print(res_delivery.stdout.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
        print("--- CLI STDERR (Delivery) ---")
        try:
            print(res_delivery.stderr)
        except UnicodeEncodeError:
            print(res_delivery.stderr.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
        
        assert res_delivery.returncode == 0, f"Expected Delivery CLI to exit with 0, got {res_delivery.returncode}"
        
        clip_subfolder = os.path.join(output_dir, "test_tape_integration")
        clip1_mp4 = os.path.join(clip_subfolder, "clip_2005-06-12_14-30-00.mp4")
        clip2_mp4 = os.path.join(clip_subfolder, "clip_2005-06-12_14-30-15.mp4")
        
        assert os.path.exists(clip1_mp4), f"Expected {clip1_mp4} to exist."
        assert os.path.getsize(clip1_mp4) > 0, f"Expected {clip1_mp4} to have non-zero file size."
        assert os.path.exists(clip2_mp4), f"Expected {clip2_mp4} to exist."
        assert os.path.getsize(clip2_mp4) > 0, f"Expected {clip2_mp4} to have non-zero file size."
        
        # Remove MP4 clips to prepare for the archive test
        os.remove(clip1_mp4)
        os.remove(clip2_mp4)
        
        # --- TEST CASE 2: Archive Profile (FFV1/FLAC MKV) ---
        print("\n--- Running Test Case 2: Archive Profile (FFV1/FLAC MKV) ---")
        cmd_archive = [
            sys.executable, "-m", "dv_transfer",
            "--input", test_filepath,
            "--output-dir", output_dir,
            "--gap-threshold", "3.0",
            "--profile", "archive"
        ]
        res_archive = subprocess.run(cmd_archive, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        
        print("\n--- CLI STDOUT (Archive) ---")
        try:
            print(res_archive.stdout)
        except UnicodeEncodeError:
            print(res_archive.stdout.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
        print("--- CLI STDERR (Archive) ---")
        try:
            print(res_archive.stderr)
        except UnicodeEncodeError:
            print(res_archive.stderr.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'))
        
        assert res_archive.returncode == 0, f"Expected Archive CLI to exit with 0, got {res_archive.returncode}"
        
        clip1_mkv = os.path.join(clip_subfolder, "clip_2005-06-12_14-30-00.mkv")
        clip2_mkv = os.path.join(clip_subfolder, "clip_2005-06-12_14-30-15.mkv")
        
        assert os.path.exists(clip1_mkv), f"Expected {clip1_mkv} to exist."
        assert os.path.getsize(clip1_mkv) > 0, f"Expected {clip1_mkv} to have non-zero file size."
        assert os.path.exists(clip2_mkv), f"Expected {clip2_mkv} to exist."
        assert os.path.getsize(clip2_mkv) > 0, f"Expected {clip2_mkv} to have non-zero file size."
        
        print("\nINTEGRATION TESTS PASSED SUCCESSFULLY! Both H.264/AAC MP4 (Delivery) and FFV1/FLAC MKV (Archive) output profiles transcoded correctly.")
        
    finally:
        # Cleanup with retry loop for Windows delayed file lock release
        import time
        for _ in range(10):
            try:
                if os.path.exists(test_filepath):
                    os.remove(test_filepath)
                if os.path.exists(output_dir):
                    shutil.rmtree(output_dir)
                break
            except PermissionError:
                time.sleep(0.5)
        print("Cleaned up integration test files.")

if __name__ == "__main__":
    main()
