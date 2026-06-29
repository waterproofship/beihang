import os
import sys
import csv
import math
import glob
import shutil
import time
import stat
from datetime import timedelta
from pathlib import Path

import gpxpy
import pandas as pd
import numpy as np
import patoolib

# ==========================================
# CONFIGURATION & FILE PATHS
# ==========================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

fname = "20260408.gpx"
sname = "0307output.csv"
labeled_sname = "labeled_track.csv"
output_csv_name = "output.csv"
rar_filename = "LiuJingLong-RUN-260408.rar"  

# The exact baseline time you manually typed in your old workflow
TARGET_BASELINE_TIME = 849.0  

# ==========================================
# HELPER: FIND RAR EXTRACTOR
# ==========================================
def get_rar_executable():
    common_paths = [
        r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe",
        r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files\WinRAR\WinRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\WinRAR.exe"
    ]
    for p in common_paths:
        if os.path.exists(p): return p
    return None

# =========================================================================================
# STEP 1: GPX PROCESSING
#
# [ MATHEMATICAL EXPLANATIONS - STEP 1 ]
# 1. Haversine Formula: Calculates the great-circle distance between two points on a 
#    sphere (Earth) given their longitudes and latitudes. It uses trigonometric functions 
#    (sin, cos, atan2) to map spherical coordinates to linear distance (meters).
# 2. Heading (Bearing): Uses the forward azimuth formula to determine the angle (0-360 deg)
#    from the true North between two coordinate points. Math uses ATAN2(x, y).
# 3. Distance Scaling: Calculates a scale factor = (Target Distance / Calculated Distance). 
#    Applies this linear ratio to every distance delta to stretch/compress the run to 
#    exactly 3114.0 meters.
# 4. Speed & Turn Rate: Calculates velocity via derivative of distance over time (d/t). 
#    Calculates angular velocity (Turn Rate) via the derivative of heading over time.
# 5. Smoothing Filter: Applies a center-weighted rolling moving average over a window size 
#    of 5 to smooth out high-frequency GPS coordinate jitter before applying the curve threshold.
#
# [ FILE PARSING & MOVEMENT EXPLANATIONS - STEP 1 ]
# 1. Reading XML: The 'gpxpy' library is used to parse the hierarchical XML structure of 
#    a .gpx file, traversing down through 'tracks' -> 'segments' -> 'points'.
# 2. Data Structuring: Extracted point objects are appended to a native Python dictionary 
#    and converted into a pandas DataFrame. This allows for fast, vectorized column math.
# 3. Data Cleansing: Corrupt GPS points tagged with the year '2026' are explicitly ignored 
#    during the file reading loop, keeping the final DataFrame clean.
# 4. File Writing: Exports the cleaned, calculated matrix to 'labeled_track.csv' using 
#    'utf-8-sig' encoding to ensure proper reading by external software.
# =========================================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0  
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def calculate_heading(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

def process_and_fix_gpx(gpx_file, min_heading_distance=0.1, target_distance=3114.0, target_time_s=849.0):
    gpx_file = Path(gpx_file)
    with open(gpx_file, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    rows = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                if pt.time and pt.time.year == 2026: continue
                rows.append({"lat": pt.latitude, "lon": pt.longitude, "elevation_m": pt.elevation})

    df = pd.DataFrame(rows)
    n_points = len(df)
    
    interval_s = target_time_s / (n_points - 1) if n_points > 1 else 0
    base_time = pd.Timestamp("1970-01-21 13:13:57.379Z")
    df["time"] = [base_time + timedelta(seconds=i * interval_s) for i in range(n_points)]

    distances_raw = [0.0]
    headings = [np.nan]
    last_valid_heading = 0.0

    for i in range(1, n_points):
        lat1, lon1 = df.loc[i - 1, "lat"], df.loc[i - 1, "lon"]
        lat2, lon2 = df.loc[i, "lat"], df.loc[i, "lon"]
        d = haversine_distance(lat1, lon1, lat2, lon2)
        distances_raw.append(d)
        if d >= min_heading_distance:
            h = calculate_heading(lat1, lon1, lat2, lon2)
            last_valid_heading = h
        else:
            h = last_valid_heading
        headings.append(h)

    calculated_total_distance = sum(distances_raw)
    scale_factor = target_distance / calculated_total_distance if calculated_total_distance > 0 else 1.0

    df["distance_m"] = [d * scale_factor for d in distances_raw]
    df["cum_distance_m"] = df["distance_m"].cumsum()
    df["dt_s"] = [0.0] + [interval_s] * (n_points - 1)
    df["speed_m_s"] = df["distance_m"] / df["dt_s"].replace(0, np.nan)
    df["speed_km_h"] = df["speed_m_s"] * 3.6
    df["heading_deg"] = headings
    df["speed_m_s"] = df["speed_m_s"].fillna(0)
    df["speed_km_h"] = df["speed_km_h"].fillna(0)
    return df

def label_track_segments(df, threshold=2.0, window_size=5):
    df["heading_deg"] = pd.to_numeric(df["heading_deg"], errors='coerce')
    heading_diff = df["heading_deg"].diff()
    heading_diff = (heading_diff + 180) % 360 - 180
    df["turn_rate_deg_s"] = heading_diff / df["dt_s"].replace(0, np.nan)
    df["turn_rate_deg_s"] = pd.to_numeric(df["turn_rate_deg_s"], errors='coerce')
    df["smoothed_turn_rate"] = df["turn_rate_deg_s"].rolling(window=window_size, center=True).mean().fillna(0)
    df["segment_type"] = np.where(df["smoothed_turn_rate"].abs() > threshold, "Curve", "Straight")
    return df

# =========================================================================================
# STEP 2: TIME INTERVAL
#
# [ MATHEMATICAL EXPLANATIONS - STEP 2 ]
# 1. Linear Time Generation: Uses a simple multiplication function (count * interval) where 
#    interval is a constant 1.9976 seconds. This effectively generates a strictly linear, 
#    monotonic time vector mapped to each incoming row index.
# 2. Hard Stop Constraint: Enforces a strict truncation mathematical limit (target_count = 426). 
#    Any iterations beyond 426 bypass the mathematical operation and pass through untouched.
#
# [ FILE PARSING & MOVEMENT EXPLANATIONS - STEP 2 ]
# 1. Memory Efficient I/O: Instead of loading the entire file into memory with Pandas, 
#    it uses Python's native 'csv' module to stream the file line-by-line using a generator 
#    (reader/writer).
# 2. Row Padding Safeguard: Implements a 'while len(row) < 4' loop. If a row parsed from 
#    the CSV has missing columns, it pads the array with empty strings. This prevents an 
#    IndexError when forcefully inserting data into the 4th column index (row[3]).
# =========================================================================================
def modify_csv_timestamps(input_filepath, output_filepath):
    interval = 1.9976
    target_count = 426
    with open(input_filepath, mode='r', newline='', encoding='utf-8') as infile, \
         open(output_filepath, mode='w', newline='', encoding='utf-8') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)
        try:
            writer.writerow(next(reader))
        except StopIteration:
            return
            
        count = 0
        for row in reader:
            if count < target_count:
                while len(row) < 4: row.append("")
                row[3] = f"{count * interval:.4f}" 
                count += 1
            writer.writerow(row)
    print(f"Step 2: Timestamps modified. {count} rows were updated in {os.path.basename(output_filepath)}.")

# =========================================================================================
# STEP 3: ISOLATED QUARANTINE EXTRACTION
#
# [ MATHEMATICAL EXPLANATIONS - STEP 3 ]
# 1. Array Counting logic: Validates if extracted folder sizes equal exactly (10, 45, 6).
#    If lengths do not mathematically match expectations, execution halts.
#
# [ FILE PARSING & MOVEMENT EXPLANATIONS - STEP 3 ]
# 1. Quarantine Paradigm: Explicitly creates a 'temp_rar_extract' folder and routes the 
#    patoolib extraction payload directly into it. This isolates the unarchived payload 
#    from the rest of the Project Directory to prevent accidentally slurping up existing 
#    similarly-named CSVs (e.g. from older tests).
# 2. Directory Traversal: Uses os.walk() to recursively navigate all subfolders inside the 
#    quarantine zone, flattening any nested folder structures created by the RAR file.
# 3. Keyword Routing: Utilizes boolean string matching (keyword in f) to distribute files.
#    'shutil.move' physically relocates the file pointers on the drive to the newly 
#    created 'imu', 'irrelevant', and 'emg' sub-directories.
# 4. OS-Level Bulldozing: Windows often applies an 'S_IWRITE' read-only permission to files 
#    extracted from archives. A custom 'remove_readonly' handler is passed into 'shutil.rmtree'
#    which uses 'os.chmod' to violently strip read-only flags so the temporary folder can 
#    be cleanly deleted. Includes a time.sleep() retry loop to bypass antivirus locks.
# =========================================================================================
def organize_and_validate_files():
    rar_path = os.path.join(PROJECT_DIR, rar_filename)
    imu_dir = os.path.join(PROJECT_DIR, "imu")
    irrelevant_dir = os.path.join(PROJECT_DIR, "irrelevant")
    emg_dir = os.path.join(PROJECT_DIR, "emg")

    os.makedirs(imu_dir, exist_ok=True)
    os.makedirs(irrelevant_dir, exist_ok=True)
    os.makedirs(emg_dir, exist_ok=True)

    emg_count = len(os.listdir(emg_dir))
    imu_count = len(os.listdir(imu_dir))
    irrelevant_count = len(os.listdir(irrelevant_dir))

    if emg_count == 10 and imu_count == 45 and irrelevant_count == 6:
        print("Step 3: Directory counts already validated. Skipping extraction.")
        return

    # 1. Create Quarantine Folder
    temp_extract_dir = os.path.join(PROJECT_DIR, "temp_rar_extract")
    os.makedirs(temp_extract_dir, exist_ok=True)

    # 2. Extract directly into the Quarantine Folder
    if os.path.exists(rar_path):
        print(f"Step 3: Extracting {rar_filename} into an isolated folder...")
        extractor_program = get_rar_executable()
        if extractor_program:
            patoolib.extract_archive(rar_path, outdir=temp_extract_dir, program=extractor_program)
        else:
            print("Error: Python could not find 7-Zip or WinRAR.")
            sys.exit(1)
    else:
        print(f"Error: {rar_filename} is missing.")
        sys.exit(1)

    time.sleep(1) 

    # 3. Pull files ONLY from the Quarantine Folder
    irrelevant_files = ["info.csv", "Ultium_EMG-Llowleg.csv", "Ultium_EMG-LUPleg.csv", 
                        "Ultium_EMG-右_pelvis.csv", "Ultium_EMG-Rlowleg.csv", "Ultium_EMG-Rupleg.csv"]
    imu_keywords = ("_Ax", "_Ay", "_Az", "_Gx", "_Gy", "_Gz", "_Mx", "_My", "_Mz")

    csvs_found = 0
    for root, dirs, files in os.walk(temp_extract_dir):
        for f in files:
            if f.endswith(".csv"):
                csvs_found += 1
                f_path = os.path.join(root, f)
                
                if any(keyword in f for keyword in imu_keywords):
                    shutil.move(f_path, os.path.join(imu_dir, f))
                elif f in irrelevant_files:
                    shutil.move(f_path, os.path.join(irrelevant_dir, f))
                else:
                    shutil.move(f_path, os.path.join(emg_dir, f))

    print(f"  -> Successfully secured {csvs_found} CSV files from the archive.")

    # 4. Annihilate the Quarantine Folder
    def remove_readonly(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception: pass
        
    for _ in range(3):
        if not os.path.exists(temp_extract_dir): break
        try: shutil.rmtree(temp_extract_dir, onerror=remove_readonly)
        except Exception: pass
        time.sleep(1)

    # 5. Final Validation
    emg_count = len(os.listdir(emg_dir))
    imu_count = len(os.listdir(imu_dir))
    irrelevant_count = len(os.listdir(irrelevant_dir))

    if emg_count == 10 and imu_count == 45 and irrelevant_count == 6:
        print("Step 3: Directory counts validated. Proceeding.")
    else:
        print(f"\n--- VALIDATION FAILED ---")
        print(f"Directory counts mismatch!")
        print(f"EMG Folder: Found {emg_count} (Expected 10)")
        print(f"IMU Folder: Found {imu_count} (Expected 45)")
        print(f"Irrelevant Folder: Found {irrelevant_count} (Expected 6)")
        print("\nirrelevant data")
        sys.exit(0)

# =========================================================================================
# STEP 4: SYNCHRONIZE
#
# [ MATHEMATICAL EXPLANATIONS - STEP 4 ]
# 1. Frequency to Time Conversion: T (Time per Count) = 1.0 / Frequency (Hz).
#    e.g., 1.0 / 200Hz = 0.005 seconds per row.
# 2. Total Elapsed Time: Total Initial Counts * Time per count. Calculates the absolute 
#    duration of the captured sensor data.
# 3. Target Offset Calculation: Subtracts the user-defined TARGET_BASELINE_TIME (849.0s) 
#    from the total duration to determine the excess time (Δt) at the start of the recording.
# 4. Rows to Drop: Uses the floor function (math.floor) to convert excess time (Δt) back 
#    into an integer row count by dividing by T (Time per count).
# 5. Zeroing Matrix Math: Subtracts a scalar value (the first valid numeric value in the 
#    time column) from the entire time column vector. This shifts the y-intercept of the 
#    time axis to precisely 0.0 without mutating internal scaling.
#
# [ FILE PARSING & MOVEMENT EXPLANATIONS - STEP 4 ]
# 1. Two-Pass Metadata Extraction: First pass strictly limits read depth (nrows=2) to quickly
#    extract frequency and count. 'errors=coerce' implicitly handles Chinese character encoding 
#    issues by ignoring unparseable text.
# 2. DataFrame Slicing (iloc): Rather than deleting rows interactively, pandas integer-location
#    based indexing (iloc) slices the matrix. header_rows isolates the top 2 elements [0:2]. 
#    data_rows isolates from [2 + rows_to_drop:] onward, completely bypassing row index 3
#    which hides the "Time" text string, avoiding ValueError crashes during mathematical updates.
# 3. Concatenation and Save: Re-attaches the preserved metadata headers to the sliced data
#    using pd.concat, ensuring structural integrity is retained for external tools.
# =========================================================================================
def sync_datasets(target_time):
    folder_path = os.path.join(PROJECT_DIR, "imu")
    csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in {folder_path}.")
        return

    valid_datasets = []
    skipped_files = []

    for file in csv_files:
        try:
            meta_df = pd.read_csv(file, header=None, nrows=2)

            if meta_df.shape[1] < 6:
                skipped_files.append((file, "Not enough columns"))
                continue

            header_freq = str(meta_df.iloc[0, 4]).strip().lower()
            
            if 'frequency' in header_freq:
                freq_value = float(meta_df.iloc[1, 4]) 

                if freq_value in [200.0, 2000.0]:
                    header_count = str(meta_df.iloc[0, 5]).strip().lower()
                    
                    if 'count' in header_count:
                        count_value = int(meta_df.iloc[1, 5]) 
                        valid_datasets.append({
                            'file': file,
                            'freq': freq_value,
                            'count': count_value
                        })
                        continue 
            
            skipped_files.append((file, "Did not match 200/2000Hz frequency or format"))

        except Exception as e:
            skipped_files.append((file, f"Parse error: {e}"))

    orig_time_folder = os.path.join(PROJECT_DIR, "Synced_Original_Time")
    zeroed_time_folder = os.path.join(PROJECT_DIR, "Synced_Zeroed_Time")

    os.makedirs(orig_time_folder, exist_ok=True)
    os.makedirs(zeroed_time_folder, exist_ok=True)

    print(f"\nStep 4: Synchronizing data to baseline time: {target_time} seconds")
    
    for data in valid_datasets:
        freq = data['freq']
        file_path = data['file']
        initial_count = data['count']
        file_name = os.path.basename(file_path)
        
        time_per_count = 1.0 / freq
        total_time = initial_count * time_per_count
        time_offset = total_time - target_time
        
        if time_offset <= 0:
            rows_to_drop = 0
            remaining_counts = initial_count
        else:
            rows_to_drop = math.floor(time_offset / time_per_count)
            remaining_counts = initial_count - rows_to_drop
            
        print(f"  -> Processing: {file_name} (Dropping: {rows_to_drop:,} | Keeping: {remaining_counts:,})")

        df_full = pd.read_csv(file_path, header=None, low_memory=False)
        
        header_rows = df_full.iloc[0:2].copy()
        header_rows.iloc[1, 5] = str(remaining_counts) 
        
        data_rows = df_full.iloc[2 + rows_to_drop:].copy()
        
        # Original Time Output
        df_orig = pd.concat([header_rows, data_rows], ignore_index=True)
        out_orig_path = os.path.join(orig_time_folder, file_name.replace('.csv', '_OriginalTime.csv'))
        df_orig.to_csv(out_orig_path, index=False, header=False)

        # Zeroed Time Output (Safety Shielded)
        data_rows_zero = data_rows.copy()
        
        # Safely convert to numbers, bypassing any leftover text strings without crashing
        time_col = pd.to_numeric(data_rows_zero[0], errors='coerce')
        if time_col.notna().any():
            start_time = time_col.dropna().iloc[0]
            data_rows_zero[0] = (time_col - start_time).round(5).fillna(data_rows_zero[0])

        df_zero = pd.concat([header_rows, data_rows_zero], ignore_index=True)
        out_zero_path = os.path.join(zeroed_time_folder, file_name.replace('.csv', '_ZeroedTime.csv'))
        df_zero.to_csv(out_zero_path, index=False, header=False)

    if skipped_files:
        print("\n--- Diagnostic: Skipped Files ---")
        for skip_file, reason in skipped_files:
            print(f"  - {os.path.basename(skip_file)}: {reason}")

# =========================================================================================
# STEP 5: COMBINE IMU
#
# [ MATHEMATICAL EXPLANATIONS - STEP 5 ]
# 1. Pure Data Passthrough: All mathematical multipliers have been completely removed.
#    - Time remains in its native unit (Seconds), incrementing exactly by 0.005 per row.
#    - Accelerometer data remains strictly in its native hardware format.
#    - Gyroscope data remains strictly in its native hardware format.
# 2. Sequential Axis Alignment: The output matrix is strictly ordered chronologically 
#    and alphabetically as requested: [Time, Ax, Ay, Az, Gx, Gy, Gz]. No axis swapping.
#
# [ FILE PARSING & MOVEMENT EXPLANATIONS - STEP 5 ]
# 1. Dynamic Sensor Routing: Uses a nested iteration loop to dynamically search the 
#    'Synced_Zeroed_Time' folder for the existence of specific suffix signatures (e.g. 
#    '_11_Ax') instead of hardcoding filenames. Allows it to scale universally to IDs 11-15.
# 2. Data Filtering: Uses 'skiprows=2' natively within pandas file I/O to explicitly bypass 
#    the metadata header rows injected in Step 4. Uses 'pd.to_numeric(errors=coerce)' as 
#    a shield to drop any residual strings (such as "Time") without raising Exceptions.
# 3. Synchronized Merge: Implements relational database-style joins. Rather than blindly 
#    stacking arrays, it merges the 6 distinct 1D Axis files based on precisely matching 
#    values in the 'Time' column, guaranteeing mathematical synchronization.
# =========================================================================================
def load_and_prep(filepath, col_name):
    # Shielded text handling ensures hash matching with original logic
    df = pd.read_csv(filepath, skiprows=2, header=None, usecols=[0, 1], names=['Time', col_name])
    df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
    df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
    return df.dropna()

def combine_imu_data():
    zeroed_dir = os.path.join(PROJECT_DIR, "Synced_Zeroed_Time")
    print("\nStep 5: Locating files for IMU Combine...")

    sensor_ids = ["11", "12", "13", "14", "15"]
    axes = ["Ax", "Ay", "Az", "Gx", "Gy", "Gz"]

    def find_file_for_sensor(sensor_id, axis):
        suffix = f"_{sensor_id}_{axis}"
        for f in os.listdir(zeroed_dir):
            if suffix in f and f.endswith("ZeroedTime.csv"):
                return os.path.join(zeroed_dir, f)
        return None

    for sid in sensor_ids:
        print(f"\n--- Building Matrix for Sensor ID: {sid} ---")
        file_paths = {}
        missing_files = False

        for axis in axes:
            found_path = find_file_for_sensor(sid, axis)
            if not found_path:
                print(f"  Error: Missing file for Sensor {sid}, Axis {axis}")
                missing_files = True
            else:
                file_paths[axis] = found_path
        
        if missing_files:
            print(f"  Skipping combination for Sensor {sid} due to missing files.")
            continue
        
        print(f"  Loading 6 axes for Sensor {sid}...")
        df_ax = load_and_prep(file_paths["Ax"], 'Accel_X')
        df_ay = load_and_prep(file_paths["Ay"], 'Accel_Y')
        df_az = load_and_prep(file_paths["Az"], 'Accel_Z')
        df_gx = load_and_prep(file_paths["Gx"], 'Gyro_X')
        df_gy = load_and_prep(file_paths["Gy"], 'Gyro_Y')
        df_gz = load_and_prep(file_paths["Gz"], 'Gyro_Z')

        print("  Merging datasets on Time alignment...")
        df_merged = df_ax.merge(df_ay, on='Time') \
                         .merge(df_az, on='Time') \
                         .merge(df_gx, on='Time') \
                         .merge(df_gy, on='Time') \
                         .merge(df_gz, on='Time')

        # Map to strictly requested layout: Time, Ax, Ay, Az, Gx, Gy, Gz
        final_matrix = df_merged[['Time', 'Accel_X', 'Accel_Y', 'Accel_Z', 'Gyro_X', 'Gyro_Y', 'Gyro_Z']]
        
        output_name = os.path.join(PROJECT_DIR, f'MATLAB_Ready_Running_Data_Full_{sid}.csv')
        final_matrix.to_csv(output_name, index=False, header=False)
        print(f"  Success! Saved pure formatted matrix to: MATLAB_Ready_Running_Data_Full_{sid}.csv")

# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
if __name__ == "__main__":
    print("--- STARTING AUTOMATED PIPELINE ---")
    
    input_gpx = os.path.join(PROJECT_DIR, fname)
    labeled_csv = os.path.join(PROJECT_DIR, labeled_sname)
    output_csv = os.path.join(PROJECT_DIR, output_csv_name)

    print(f"Step 1: Reading GPX data from {fname}...")
    df_fixed = process_and_fix_gpx(input_gpx, min_heading_distance=0.1)
    df_labeled = label_track_segments(df_fixed, threshold=2.0, window_size=5)
    df_labeled.to_csv(labeled_csv, index=False, encoding="utf-8-sig")

    modify_csv_timestamps(labeled_csv, output_csv)
    organize_and_validate_files()
    
    # Synchronize using the specific hardcoded baseline for math precision
    sync_datasets(TARGET_BASELINE_TIME)
    
    combine_imu_data()
    
    print("\n--- CLEANUP ---")
    if os.path.exists(labeled_csv):
        try:
            os.remove(labeled_csv)
            print(f"Success: Deleted temporary file '{labeled_sname}'.")
        except Exception as e:
            print(f"Warning: Could not delete '{labeled_sname}'. Error: {e}")
            
    print("\n--- PIPELINE COMPLETE ---")