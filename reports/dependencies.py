"""Bounded, fail-fast access to optional document conversion tooling."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import fcntl

from django.conf import settings


class DependencyUnavailable(RuntimeError):
    """The optional dependency is overloaded or temporarily unhealthy."""


class CircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_seconds=60, max_concurrent=1):
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()
        self._capacity = threading.BoundedSemaphore(max_concurrent)
        self._lock_path = Path(getattr(settings, "DOCUMENT_CONVERTER_LOCK_PATH", "/tmp/arl-document-converter.lock"))

    def call(self, operation):
        now = time.monotonic()
        with self._lock:
            if now < self._open_until:
                raise DependencyUnavailable("Document preview conversion is temporarily unavailable. Please try again shortly.")
        if not self._capacity.acquire(blocking=False):
            raise DependencyUnavailable("Document preview conversion is busy. Please try again shortly.")
        process_lock = self._lock_path.open("a+")
        try:
            try:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DependencyUnavailable("Document preview conversion is busy. Please try again shortly.") from exc
            result = operation()
        except (OSError, subprocess.TimeoutExpired) as exc:
            with self._lock:
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._open_until = time.monotonic() + self.recovery_seconds
            raise DependencyUnavailable("Document preview conversion failed. Please try again shortly.") from exc
        else:
            with self._lock:
                self._failures = 0
                self._open_until = 0.0
            return result
        finally:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
            process_lock.close()
            self._capacity.release()


document_converter = CircuitBreaker(
    failure_threshold=getattr(settings, "DOCUMENT_CONVERTER_FAILURE_THRESHOLD", 3),
    recovery_seconds=getattr(settings, "DOCUMENT_CONVERTER_RECOVERY_SECONDS", 60),
    max_concurrent=getattr(settings, "DOCUMENT_CONVERTER_MAX_CONCURRENT", 1),
)


def run_document_conversion(command):
    """Run LibreOffice with a bounded wait and circuit-breaker protection."""
    def operation():
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=getattr(settings, "DOCUMENT_CONVERTER_TIMEOUT_SECONDS", 20),
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="ignore").strip()
            raise OSError(detail or "LibreOffice exited unsuccessfully")
        return result

    return document_converter.call(
        operation
    )
