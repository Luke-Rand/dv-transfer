import os
from collections import Counter

def detect_dv_format(filepath):
    """
    Auto-detects whether the file is NTSC or PAL.
    NTSC frames are exactly 120,000 bytes.
    PAL frames are exactly 144,000 bytes.
    Returns (frame_size, format_name, frame_rate) or (None, None, None).
    """
    if not os.path.exists(filepath):
        return None, None, None
        
    file_size = os.path.getsize(filepath)
    if file_size < 144000:
        return None, None, None
        
    with open(filepath, 'rb') as f:
        data = f.read(144000 * 2)
        
    # NTSC Alignment Check
    # Verify if sequence headers (SCT=0) align every 12,000 bytes for 10 sequences (120,000 bytes)
    is_ntsc = True
    for i in range(10):
        off = i * 12000
        if off >= len(data):
            is_ntsc = False
            break
        if (data[off] >> 5) != 0:  # Section Type (SCT) should be 0
            is_ntsc = False
            break
    
    # Check if the next NTSC frame also starts with a header block
    if is_ntsc and len(data) >= 120000:
        if (data[120000] >> 5) != 0:
            is_ntsc = False
            
    if is_ntsc:
        return 120000, "NTSC", 29.97

    # PAL Alignment Check
    # Verify if sequence headers align every 12,000 bytes for 12 sequences (144,000 bytes)
    is_pal = True
    for i in range(12):
        off = i * 12000
        if off >= len(data):
            is_pal = False
            break
        if (data[off] >> 5) != 0:
            is_pal = False
            break
            
    # Check if the next PAL frame also starts with a header block
    if is_pal and len(data) >= 144000:
        if (data[144000] >> 5) != 0:
            is_pal = False
            
    if is_pal:
        return 144000, "PAL", 25.0

    # Fallback to NTSC if detection fails but format is DV
    return 120000, "NTSC", 29.97

def decode_timecode(pack):
    """
    Decodes a 5-byte timecode pack (0x13).
    Returns f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}" or None if invalid.
    """
    if len(pack) < 5 or pack[0] != 0x13:
        return None
        
    pc1, pc2, pc3, pc4 = pack[1], pack[2], pack[3], pack[4]
    
    # BCD digit check: lower nibble should be 0-9
    if (pc1 & 0x0F) > 9 or (pc2 & 0x0F) > 9 or (pc3 & 0x0F) > 9 or (pc4 & 0x0F) > 9:
        return None
        
    frames = (pc1 & 0x0F) + ((pc1 >> 4) & 0x03) * 10
    seconds = (pc2 & 0x0F) + ((pc2 >> 4) & 0x07) * 10
    minutes = (pc3 & 0x0F) + ((pc3 >> 4) & 0x07) * 10
    hours = (pc4 & 0x0F) + ((pc4 >> 4) & 0x03) * 10
    
    # Validate ranges
    if frames >= 30 or seconds >= 60 or minutes >= 60 or hours >= 24:
        return None
        
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

def decode_recdate(pack):
    """
    Decodes a 5-byte recording date pack (0x62 or 0x52).
    Returns f"{year:04d}-{month:02d}-{day:02d}" or None if invalid.
    """
    if len(pack) < 5 or pack[0] not in (0x62, 0x52):
        return None
        
    pc2, pc3, pc4 = pack[2], pack[3], pack[4]
    
    # BCD check
    if (pc2 & 0x0F) > 9 or (pc3 & 0x0F) > 9 or (pc4 & 0x0F) > 9:
        return None
        
    day = (pc2 & 0x0F) + ((pc2 >> 4) & 0x03) * 10
    month = (pc3 & 0x0F) + ((pc3 >> 4) & 0x01) * 10
    year_val = (pc4 & 0x0F) + ((pc4 >> 4) & 0x0F) * 10
    
    if day == 0 or day > 31 or month == 0 or month > 12:
        return None
        
    # Year logic: 00-79 is 2000-2079, 80-99 is 1980-1999
    year = 2000 + year_val if year_val < 80 else 1900 + year_val
    return f"{year:04d}-{month:02d}-{day:02d}"

def decode_rectime(pack):
    """
    Decodes a 5-byte recording time pack (0x63 or 0x53).
    Returns f"{hours:02d}:{minutes:02d}:{seconds:02d}" (excluding frames for simplicity) or None.
    """
    if len(pack) < 5 or pack[0] not in (0x63, 0x53):
        return None
        
    pc1, pc2, pc3, pc4 = pack[1], pack[2], pack[3], pack[4]
    
    if (pc1 & 0x0F) > 9 or (pc2 & 0x0F) > 9 or (pc3 & 0x0F) > 9 or (pc4 & 0x0F) > 9:
        return None
        
    seconds = (pc2 & 0x0F) + ((pc2 >> 4) & 0x07) * 10
    minutes = (pc3 & 0x0F) + ((pc3 >> 4) & 0x07) * 10
    hours = (pc4 & 0x0F) + ((pc4 >> 4) & 0x03) * 10
    
    if seconds >= 60 or minutes >= 60 or hours >= 24:
        return None
        
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def parse_frame_metadata(frame_bytes, num_sequences):
    """
    Scans the Subcode and VAUX areas of a frame to extract Timecodes, RecDates, and RecTimes.
    Performs majority voting to ensure resilience against bit errors.
    Returns (timecode, rec_date, rec_time).
    """
    timecodes = []
    rec_dates = []
    rec_times = []
    
    for s in range(num_sequences):
        seq_off = s * 12000
        if seq_off + 480 > len(frame_bytes):
            break
            
        # 1. Parse Subcode Block 0 (block 1, offset 80)
        # Holds 6 packs at offsets 86 + j * 8
        for j in range(6):
            pack_off = seq_off + 86 + j * 8
            pack = frame_bytes[pack_off : pack_off + 5]
            if pack[0] == 0x13:
                tc = decode_timecode(pack)
                if tc: timecodes.append(tc)
                
        # 2. Parse Subcode Block 1 (block 2, offset 160)
        # Holds 6 packs at offsets 166 + j * 8
        for j in range(6):
            pack_off = seq_off + 166 + j * 8
            pack = frame_bytes[pack_off : pack_off + 5]
            if pack[0] == 0x13:
                tc = decode_timecode(pack)
                if tc: timecodes.append(tc)
                
        # 3. Parse VAUX Block 0, 1, 2 (blocks 3, 4, 5 at offsets 240, 320, 400)
        # Each block holds 15 packs of 5 bytes spaced at 3 + p * 5
        for b in (240, 320, 400):
            for p in range(15):
                pack_off = seq_off + b + 3 + p * 5
                pack = frame_bytes[pack_off : pack_off + 5]
                
                # Check for recdate (0x62 or 0x52)
                if pack[0] in (0x62, 0x52):
                    date_str = decode_recdate(pack)
                    if date_str: rec_dates.append(date_str)
                    
                # Check for rectime (0x63 or 0x53)
                elif pack[0] in (0x63, 0x53):
                    time_str = decode_rectime(pack)
                    if time_str: rec_times.append(time_str)
                    
    # Majority voting to pick the best representation
    best_tc = Counter(timecodes).most_common(1)[0][0] if timecodes else None
    best_date = Counter(rec_dates).most_common(1)[0][0] if rec_dates else None
    best_time = Counter(rec_times).most_common(1)[0][0] if rec_times else None
    
    return best_tc, best_date, best_time

def parse_dv_file(filepath, progress_callback=None):
    """
    Parses a raw DV file frame by frame.
    Generates a list of dictionaries, one per frame:
    {
      'frame_index': int,
      'timecode': str or None,
      'rec_date': str or None,
      'rec_time': str or None,
      'is_valid': bool
    }
    """
    frame_size, format_name, frame_rate = detect_dv_format(filepath)
    if not frame_size:
        raise ValueError(f"File {filepath} is not a valid DV stream or is too small.")
        
    num_sequences = frame_size // 12000
    file_size = os.path.getsize(filepath)
    total_frames = file_size // frame_size
    
    frames_metadata = []
    
    with open(filepath, 'rb') as f:
        for idx in range(total_frames):
            frame_bytes = f.read(frame_size)
            if len(frame_bytes) < frame_size:
                break
                
            tc, date_str, time_str = parse_frame_metadata(frame_bytes, num_sequences)
            
            # A frame is valid if it contains a valid timecode or datecode
            is_valid = (tc is not None) or (date_str is not None)
            
            frames_metadata.append({
                'frame_index': idx,
                'timecode': tc,
                'rec_date': date_str,
                'rec_time': time_str,
                'is_valid': is_valid
            })
            
            if progress_callback and idx % 100 == 0:
                progress_callback(idx, total_frames)
                
    if progress_callback:
        progress_callback(total_frames, total_frames)
        
    return frames_metadata, frame_rate

def timecode_to_frames(tc_str, frame_rate):
    """
    Converts a timecode string 'hh:mm:ss:ff' to absolute frames.
    Handles NTSC drop-frame standard if frame_rate is ~29.97.
    """
    if not tc_str:
        return None
    try:
        parts = tc_str.split(':')
        if len(parts) != 4:
            return None
        h, m, s, f = map(int, parts)
        
        fps_int = int(round(frame_rate))
        if fps_int == 25:  # PAL
            return h * 3600 * 25 + m * 60 * 25 + s * 25 + f
            
        # NTSC (29.97 fps) drop-frame conversion
        # Drop frame drops numbers 0 and 1 of the first second of every minute,
        # except when the minute is a multiple of 10.
        total_minutes = h * 60 + m
        total_frames = (total_minutes * 60 + s) * 30 + f
        dropped_frames = 2 * (total_minutes - total_minutes // 10)
        return total_frames - dropped_frames
    except Exception:
        return None

def is_continuous(meta1, meta2, frame_rate):
    """
    Checks if meta2 is continuous with meta1 by comparing frame index diff with timecode frame diff.
    """
    if not meta1['timecode'] or not meta2['timecode']:
        return False
        
    tc1 = timecode_to_frames(meta1['timecode'], frame_rate)
    tc2 = timecode_to_frames(meta2['timecode'], frame_rate)
    
    if tc1 is None or tc2 is None:
        return False
        
    d_idx = meta2['frame_index'] - meta1['frame_index']
    d_tc = tc2 - tc1
    
    # In continuous playback, d_tc should match d_idx.
    # Allow a tolerance of up to 5 frames for drop-frame differences/jitters.
    return abs(d_tc - d_idx) <= 5

def detect_recorded_segments(frames_metadata, frame_rate, gap_threshold_seconds=1.0):
    """
    Groups contiguous valid frames into recorded segments by checking for timecode continuity.
    A segment is split if:
    1. The timecode value jumps/discontinues.
    2. The timecode is missing for more than gap_threshold_seconds.
    
    Tiny dropouts of missing timecode (less than gap_threshold_seconds) are smoothed
    over if the timecode before and after the dropout is continuous.
    """
    max_gap_frames = int(gap_threshold_seconds * frame_rate)
    if max_gap_frames < 2:
        max_gap_frames = 15  # Default to ~0.5 seconds if threshold is too small
        
    segments = []
    n = len(frames_metadata)
    i = 0
    
    while i < n:
        # 1. Find the start of the next segment (first frame with valid timecode)
        if not frames_metadata[i]['timecode']:
            i += 1
            continue
            
        segment_start = i
        last_valid_idx = i
        i += 1
        
        # 2. Consume frames in the current segment
        while i < n:
            meta_curr = frames_metadata[i]
            
            if meta_curr['timecode']:
                # Check continuity with last_valid_idx
                if is_continuous(frames_metadata[last_valid_idx], meta_curr, frame_rate):
                    last_valid_idx = i
                    i += 1
                else:
                    # Discontinuity (timecode jump) -> End current segment, start new one
                    segments.append((segment_start, last_valid_idx))
                    break  # Break inner loop, i will point to the start of the next segment
            else:
                # Missing timecode. Check if it's a temporary dropout or a real gap.
                # Look ahead up to max_gap_frames
                found_next_valid = False
                lookahead_limit = min(i + max_gap_frames, n)
                for j in range(i, lookahead_limit):
                    if frames_metadata[j]['timecode']:
                        # Found a valid timecode. Check if it is continuous with last_valid_idx
                        if is_continuous(frames_metadata[last_valid_idx], frames_metadata[j], frame_rate):
                            # It's a dropout! Smooth over it.
                            last_valid_idx = j
                            i = j + 1
                            found_next_valid = True
                        else:
                            # It's a jump after a short gap.
                            # End current segment at last_valid_idx.
                            # Next segment will start at j.
                            segments.append((segment_start, last_valid_idx))
                            i = j  # i now points to the new segment start
                            found_next_valid = True
                        break
                
                if found_next_valid:
                    # We updated i and last_valid_idx, so we continue the inner loop
                    continue
                else:
                    # No valid timecode found within the lookahead window.
                    # This is a real gap (blank tape).
                    # End the current segment at last_valid_idx.
                    segments.append((segment_start, last_valid_idx))
                    i += max_gap_frames  # Skip the gap window we already searched
                    break  # Break inner loop to search for next segment start
                    
        # If we reached the end of the file and still in a segment
        else:
            # Inner loop finished without 'break' (reached end of tape)
            segments.append((segment_start, last_valid_idx))
            
    # Convert segments to detailed dicts
    detailed_segments = []
    for start, end in segments:
        start_tc = frames_metadata[start]['timecode']
        end_tc = frames_metadata[end]['timecode']
        start_date = None
        start_time = None
        for k in range(start, end + 1):
            meta = frames_metadata[k]
            if not start_date and meta['rec_date']:
                start_date = meta['rec_date']
            if not start_time and meta['rec_time']:
                start_time = meta['rec_time']
            if start_date and start_time:
                break
                
        start_datetime = None
        if start_date:
            time_part = start_time if start_time else "00:00:00"
            start_datetime = f"{start_date} {time_part}"
            
        duration = (end - start + 1) / frame_rate
        
        detailed_segments.append({
            'start_frame': start,
            'end_frame': end,
            'start_timecode': start_tc,
            'end_timecode': end_tc,
            'start_datetime': start_datetime,
            'duration_seconds': duration
        })
        
    return detailed_segments
