import math
from collections import deque
from typing import Deque, List, Optional


class RollingBaseline:
    """Calculates a deterministic rolling window average baseline.

    Maintains the most recent `window_size` samples and computes an unweighted
    arithmetic mean once at least `min_samples` historical points have been recorded.
    """

    def __init__(self, window_size: int = 10, min_samples: int = 3):
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise ValueError("window_size must be an integer, not a boolean.")
        if isinstance(min_samples, bool) or not isinstance(min_samples, int):
            raise ValueError("min_samples must be an integer, not a boolean.")
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {window_size}")
        if min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {min_samples}")
        if min_samples > window_size:
            raise ValueError(
                f"min_samples ({min_samples}) cannot exceed window_size ({window_size})"
            )

        self.window_size = window_size
        self.min_samples = min_samples
        self._samples: Deque[float] = deque(maxlen=window_size)

    @property
    def sample_count(self) -> int:
        """Current number of stored samples in the rolling window."""
        return len(self._samples)

    @property
    def is_ready(self) -> bool:
        """True if the number of recorded samples satisfies min_samples."""
        return len(self._samples) >= self.min_samples

    @property
    def value(self) -> Optional[float]:
        """Current rolling average, or None if insufficient samples exist."""
        if not self.is_ready:
            return None
        return sum(self._samples) / len(self._samples)

    def add(self, value: float) -> None:
        """Add a normal measurement to the rolling baseline window."""
        if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
            raise ValueError(f"Invalid measurement: {value}. Measurement cannot be a boolean and must be a finite number.")
        self._samples.append(float(value))

    def get_history(self) -> List[float]:
        """Return a snapshot copy of current historical samples in chronological order."""
        return list(self._samples)

    def clear(self) -> None:
        """Reset the baseline window."""
        self._samples.clear()


class EWMABaseline:
    """Calculates an Exponentially Weighted Moving Average (EWMA) baseline.

    Formula:
        EWMA(t) = alpha * current_value + (1 - alpha) * previous_EWMA

    Where:
        - alpha in (0, 1] controls weight assigned to the most recent measurement.
        - Initialized with the first observed measurement: EWMA(0) = current_value.
    """

    def __init__(self, alpha: float = 0.3, min_samples: int = 3):
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            raise ValueError("alpha must be numeric and cannot be a boolean.")
        if isinstance(min_samples, bool) or not isinstance(min_samples, int):
            raise ValueError("min_samples must be an integer, not a boolean.")
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in the range (0, 1], got {alpha}")
        if min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {min_samples}")

        self.alpha = float(alpha)
        self.min_samples = min_samples
        self._ewma: Optional[float] = None
        self._sample_count: int = 0

    @property
    def sample_count(self) -> int:
        """Number of samples incorporated into the current EWMA estimate."""
        return self._sample_count

    @property
    def is_ready(self) -> bool:
        """True if sample_count meets min_samples."""
        return self._sample_count >= self.min_samples

    @property
    def value(self) -> Optional[float]:
        """Current EWMA baseline value, or None if insufficient samples exist."""
        if not self.is_ready or self._ewma is None:
            return None
        return self._ewma

    def add(self, value: float) -> float:
        """Incorporate a new normal measurement into the EWMA estimate."""
        if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
            raise ValueError(f"Invalid measurement: {value}. Measurement cannot be a boolean and must be a finite number.")

        val = float(value)
        if self._ewma is None:
            self._ewma = val
        else:
            self._ewma = (self.alpha * val) + ((1.0 - self.alpha) * self._ewma)

        self._sample_count += 1
        return self._ewma

    def clear(self) -> None:
        """Reset the EWMA state."""
        self._ewma = None
        self._sample_count = 0

