import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, find_peaks
from scipy.interpolate import interp1d

# ==========================================
# 1. LOAD MASTER DATASET
# ==========================================
# File has 7 columns: Time, Ax, Ay, Az, Gx, Gy, Gz (No headers)
df = pd.read_csv('MATLAB_Ready_Running_Data_Full_14.csv', header=None)

time = df[0].values
ax = df[1].values
ay = df[2].values
az = df[3].values  # Master Signal chosen for peak identification
gx = df[4].values
gy = df[5].values
gz = df[6].values

fs = 200.0  # Sampling frequency (200 Hz)

# ==========================================
# 2. ZERO-PHASE BUTTERWORTH BANDPASS FILTER
# ==========================================
def butter_bandpass_filter(data, lowcut, highcut, fs, order=4):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, data)

# Filter the Vertical Acceleration to serve as the clean Master Signal
az_filtered = butter_bandpass_filter(az, 0.5, 20.0, fs, order=4)

# ==========================================
# 3. ADAPTIVE STEP & CYCLE SEGMENTATION
# ==========================================
# distance=int(0.4 * fs) prevents double-triggering within 400ms
peaks, _ = find_peaks(az_filtered, distance=int(0.4 * fs), prominence=2000)
num_cycles = len(peaks) - 1
print(f"Successfully extracted {num_cycles} synchronized gait cycles!")

# ==========================================
# 4. EXTRACT & EXPORT CYCLE DURATIONS
# ==========================================
# Calculate the duration of each cycle in seconds
cycle_durations = np.diff(time[peaks])

# Print a quick statistical summary
print(f"\n--- Gait Cycle Duration Stats ---")
print(f"Total Cycles:     {num_cycles}")
print(f"Average Duration: {np.mean(cycle_durations):.4f} seconds")
print(f"Shortest Cycle:   {np.min(cycle_durations):.4f} seconds")
print(f"Longest Cycle:    {np.max(cycle_durations):.4f} seconds")
print(f"Standard Dev:     {np.std(cycle_durations):.4f} seconds\n")

# Export to CSV
durations_df = pd.DataFrame({
    'Cycle_Number': np.arange(1, num_cycles + 1),
    'Duration_Seconds': cycle_durations
})
durations_df.to_csv('Gait_Cycle_Durations.csv', index=False)
print("Saved Gait_Cycle_Durations.csv successfully.")

# ==========================================
# 5. UNIVERSAL TIME NORMALIZATION (0-100%)
# ==========================================
gait_percent = np.linspace(0, 100, 101)
# Create data structures to hold 101-point curves for all 6 channels
normalized_data = {ch: np.zeros((num_cycles, 101)) for ch in range(1, 7)}

for idx in range(num_cycles):
    start_idx = peaks[idx]
    end_idx = peaks[idx+1]
    
    # Real time vector for this isolated stride
    stride_time = time[start_idx:end_idx+1]
    # Normalize real-time into a 0 to 100 percentage scale
    t_norm = (stride_time - stride_time[0]) / (stride_time[-1] - stride_time[0]) * 100
    
    # Slices all 6 channels simultaneously using the exact same frame window
    for ch in range(1, 7):
        raw_slice = df[ch].values[start_idx:end_idx+1]
        # Mathematical interpolation to standard 101 points
        f_interp = interp1d(t_norm, raw_slice, kind='cubic')
        normalized_data[ch][idx, :] = f_interp(gait_percent)

# Calculate Ensemble Means and Standard Deviations
means = {ch: np.mean(normalized_data[ch], axis=0) for ch in range(1, 7)}
stds = {ch: np.std(normalized_data[ch], axis=0) for ch in range(1, 7)}

# ==========================================
# 6. VISUALIZATION GENERATION
# ==========================================
channel_labels = {1: 'Ax', 2: 'Ay', 3: 'Az', 4: 'Gx', 5: 'Gy', 6: 'Gz'}

# Plot 1: Linear Accelerations (Ax, Ay, Az)
fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
accel_colors = {1: 'crimson', 2: 'forestgreen', 3: 'blue'}
for i, ch in enumerate([1, 2, 3]):
    axes[i].plot(gait_percent, means[ch], color=accel_colors[ch], lw=2, label='Ensemble Mean')
    axes[i].fill_between(gait_percent, means[ch] - stds[ch], means[ch] + stds[ch], 
                         color=accel_colors[ch], alpha=0.18, label='±1 Std Dev')
    axes[i].set_ylabel('Acceleration (mG)', fontsize=11)
    axes[i].set_title(f'Ensemble Average Gait Cycle: {channel_labels[ch]}', fontsize=12)
    axes[i].grid(True, linestyle='--', alpha=0.5)
    axes[i].legend(loc='upper right')
axes[2].set_xlabel('Gait Cycle (%)', fontsize=12)
plt.tight_layout()
plt.savefig('gait_cycle_acceleration.png', dpi=150)
plt.close()

# Plot 2: Angular Velocities (Gx, Gy, Gz)
fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
gyro_colors = {4: 'darkorange', 5: 'purple', 6: 'teal'}
for i, ch in enumerate([4, 5, 6]):
    axes[i].plot(gait_percent, means[ch], color=gyro_colors[ch], lw=2, label='Ensemble Mean')
    axes[i].fill_between(gait_percent, means[ch] - stds[ch], means[ch] + stds[ch], 
                         color=gyro_colors[ch], alpha=0.18, label='±1 Std Dev')
    axes[i].set_ylabel('Angular Velocity (deg/s)', fontsize=11)
    axes[i].set_title(f'Ensemble Average Gait Cycle: {channel_labels[ch]}', fontsize=12)
    axes[i].grid(True, linestyle='--', alpha=0.5)
    axes[i].legend(loc='upper right')
axes[2].set_xlabel('Gait Cycle (%)', fontsize=12)
plt.tight_layout()
plt.savefig('gait_cycle_gyroscope.png', dpi=150)
plt.close()

# ==========================================
# 7. EXPORT STATISTICAL DATA SUMMARY
# ==========================================
summary_df = pd.DataFrame({'Gait_Cycle_Percent': gait_percent})
for ch in range(1, 7):
    lbl = channel_labels[ch]
    summary_df[f'{lbl}_Mean'] = means[ch]
    summary_df[f'{lbl}_Std'] = stds[ch]
summary_df.to_csv('Ensemble_Average_Gait_Cycles.csv', index=False)
print("Saved Ensemble_Average_Gait_Cycles.csv successfully.")