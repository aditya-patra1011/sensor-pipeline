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
    mean = data.mean(axis=1, keepdims=True)
    std = data.std(axis=1, keepdims=True)

    z_scores = (data - mean) / std
    return np.abs(z_scores) > z_thresh


def summarize(data, anomaly_mask):
    """
    Print a per-sensor summary: mean, std, and count of anomalies.
    """
    num_sensors = data.shape[0]
    for i in range(num_sensors):
        sensor_mean = data[i].mean()
        sensor_std = data[i].std()
        anomaly_count = anomaly_mask[i].sum()
        print(
            f"Sensor {i}: mean={sensor_mean:.2f}  "
            f"std={sensor_std:.2f}  anomalies={anomaly_count}"
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

