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

def detect_recorded_segments(frames_metadata, frame_rate, gap_threshold_seconds=3.0):
    """
    Groups contiguous valid frames into recorded segments, splitting them
    by gaps of blank tape longer than gap_threshold_seconds.
    Tiny dropout frames are automatically smoothed over.
    
    Returns a list of segments:
    [
      {
        'start_frame': int,
        'end_frame': int,
        'start_timecode': str or None,
        'end_timecode': str or None,
        'start_datetime': str or None,
        'duration_seconds': float
      },
      ...
    ]
    """
    gap_threshold_frames = int(gap_threshold_seconds * frame_rate)
    segments = []
    
    in_segment = False
    segment_start = None
    blank_count = 0
    
    for i, meta in enumerate(frames_metadata):
        is_valid = meta['is_valid']
        
        if is_valid:
            if not in_segment:
                in_segment = True
                segment_start = i
            blank_count = 0
        else:
            if in_segment:
                blank_count += 1
                if blank_count >= gap_threshold_frames:
                    # Segment ends just before the blank frames started
                    segment_end = i - blank_count
                    segments.append((segment_start, segment_end))
                    in_segment = False
                    blank_count = 0
                    
    # Append the final active segment if there is one
    if in_segment:
        segments.append((segment_start, len(frames_metadata) - 1))
        
    # Build detailed segment dictionary metadata
    detailed_segments = []
    for start, end in segments:
        # Find first valid timecode and date in the segment
        start_tc = None
        start_date = None
        start_time = None
        for i in range(start, end + 1):
            meta = frames_metadata[i]
            if not start_tc and meta['timecode']:
                start_tc = meta['timecode']
            if not start_date and meta['rec_date']:
                start_date = meta['rec_date']
            if not start_time and meta['rec_time']:
                start_time = meta['rec_time']
            if start_tc and start_date and start_time:
                break
                
        end_tc = None
        for i in range(end, start - 1, -1):
            meta = frames_metadata[i]
            if not end_tc and meta['timecode']:
                end_tc = meta['timecode']
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
