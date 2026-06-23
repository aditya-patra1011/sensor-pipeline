"""
sensor_pipeline.py

A small data-processing pipeline that simulates readings from
temperature sensors (e.g. IoT devices in a warehouse), cleans them,
and flags anomalies.

Run it with:  python sensor_pipeline.py
"""

import numpy as np


def generate_sensor_data(num_sensors=5, num_readings=20, seed=42):
    """
    Simulate readings from `num_sensors` sensors, each producing
    `num_readings` readings. Returns a 2D array of shape
    (num_sensors, num_readings).

    A few readings are deliberately corrupted with NaN to simulate
    sensor dropout, and a few are deliberately set to extreme values
    to simulate faulty hardware spikes.
    """
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=25.0, scale=3.0, size=(num_sensors, num_readings))

    # simulate dropout: randomly knock out ~5% of readings
    dropout_mask = rng.random(data.shape) < 0.05
    data[dropout_mask] = np.nan

    # simulate hardware spikes: a couple of wildly wrong readings
    data[0, 3] = 150.0
    data[2, 10] = -40.0

    return data


def clean_data(data):
    """
    Replace NaN values with the mean of their own sensor's
    valid readings (row-wise mean imputation).
    """
    cleaned = data.copy()


    #IQR spike removal per sensor
    for i in range(cleaned.shape[0]):
        row = cleaned[i]
        q1 = np.nanpercentile(row, 25)
        q3 = np.nanpercentile(row, 75)
        iqr = q3 - q1
        lower, upper = q1 - 3.0 * iqr, q3 + 3.0 * iqr
        spike_mask = (row < lower) | (row > upper)
        cleaned[i, spike_mask] = np.nan
    # Mean Imputation     
    row_means = np.nanmean(cleaned, axis=1)
    for i in range(cleaned.shape[0]):
        nan_mask = np.isnan(cleaned[i])
        cleaned[i, nan_mask] = row_means[i]

    return cleaned


def flag_anomalies(data, z_thresh=2.5):
    """
    Flag readings that are more than `z_thresh` standard deviations
    away from their sensor's own mean. Returns a boolean mask of the
    same shape as `data`, True where a reading is anomalous.
    """
    global_std = data.std()
    anomaly_mask = np.zeros(data.shape, dtype=bool)

    for i in range(data.shape[0]):
        row = data[i]
        sensor_std = row.std()
        adaptive_thresh = z_thresh * (sensor_std / global_std)
        adaptive_thresh = np.clip(adaptive_thresh, 2.0, 4.0)

        mean = row.mean()
        z_scores = np.abs((row - mean) / sensor_std) if sensor_std > 0 else np.zeros_like(row)
        anomaly_mask[i] = z_scores > adaptive_thresh

    return anomaly_mask


def summarize(data, anomaly_mask):
    """
    Print a per-sensor summary: mean, std, and count of anomalies.
    """
    print(f"{'Sensor':<8} {'Mean':>7} {'Std':>7} {'Min':>7} {'Max':>7} {'Anomalies':>10} {'Rate%':>7}")
    print("-" * 60)
    for i in range(data.shape[0]):
        row = data[i]
        anomaly_count = anomaly_mask[i].sum()
        rate = 100.0 * anomaly_count / len(row)
        print(
            f"Sensor {i}  "
            f"{row.mean():>7.2f} "
            f"{row.std():>7.2f} "
            f"{row.min():>7.2f} "
            f"{row.max():>7.2f} "
            f"{anomaly_count:>10} "
            f"{rate:>6.1f}%"
        )


def main():
    raw = generate_sensor_data()
    print("Raw data (NaN = dropout):")
    print(np.round(raw, 1))
    print()

    cleaned = clean_data(raw)
    print("Cleaned data:")
    print(np.round(cleaned, 1))
    print()

    anomalies = flag_anomalies(cleaned)
    print("Summary:")
    summarize(cleaned, anomalies)


if __name__ == "__main__":
    main()

