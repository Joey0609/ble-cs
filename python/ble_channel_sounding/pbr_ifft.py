"""IFFT range profile from the complex PBR channel products.

The channel grid is spaced by 1 MHz. Missing channels remain zero instead of
being interpolated, and zero padding samples the resulting range profile more
finely. The complex products have already been corrected per tone pair by
``analyze_pbr`` before they are averaged by channel.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .results import PbrAnalysis, SPEED_OF_LIGHT_M_S

CHANNEL_SPACING_HZ = 1e6
FFT_SIZE = 4096


@dataclass(frozen=True)
class IfftRange:
    distances_m: np.ndarray
    magnitude: np.ndarray
    peak_distance_m: float
    peak_magnitude: float


def ifft_range(analysis: PbrAnalysis, fft_size: int = FFT_SIZE) -> IfftRange | None:
    """Return the positive-delay range profile of the corrected PBR product.

    The profile magnitude is normalized by the sum of product magnitudes, so a
    perfectly coherent single path peaks near one. A 1 MHz channel grid has a
    149.9 m unambiguous range; zero padding refines the displayed peak position
    but does not improve the physical bandwidth resolution.
    """
    points = analysis.points
    if len(points) < 2 or points[-1].channel - points[0].channel >= fft_size:
        return None
    spectrum = np.zeros(fft_size, dtype=np.complex128)
    for point in points:
        spectrum[point.channel - points[0].channel] = point.corrected
    weight = sum(abs(point.corrected) for point in points)
    if not weight:
        return None
    magnitude = np.abs(np.fft.ifft(spectrum)) * fft_size / weight
    distances = np.arange(fft_size) * SPEED_OF_LIGHT_M_S / (2 * CHANNEL_SPACING_HZ * fft_size)
    peak = int(np.argmax(magnitude))
    return IfftRange(distances, magnitude, float(distances[peak]), float(magnitude[peak]))
