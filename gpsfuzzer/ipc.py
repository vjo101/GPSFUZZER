"""Versioned GPS SITL command/status block over System V shared memory.

The packed little-endian wire layout is intentionally independent of the
host's native C/Python structure alignment. Keep the corresponding C++ packed
declarations synchronized with these formats.
"""

from dataclasses import dataclass
import ctypes
import math
import os
import struct
import time

from .config import DriftMode
from .drift import EffectiveDrift

GPS_SHM_KEY = 0x47505346  # ASCII "GPSF", distinct from IMUFuzzer keys.
WIRE_MAGIC = 0x47505346
WIRE_VERSION = 1
FLAG_ACTIVE = 1
MODE_COHERENT = 0
MODE_POSITION_ONLY = 1
STATE_STARTING = 0
STATE_READY = 1
STATE_INVALID = 2
STATE_STALE = 3

# command: magic, version, byte-size, seq, experiment, flags, mode,
#          delay_us, speed_mps, bearing_deg, published_monotonic_ns, ttl_ns
COMMAND_FORMAT = struct.Struct("<IHHQQIIqddQQ")
# status: magic, version, byte-size, acknowledged seq, state, error,
#         last simulation time (us), heartbeat monotonic ns, status generation
STATUS_FORMAT = struct.Struct("<IHHQIIQQQ")
STATUS_OFFSET = COMMAND_FORMAT.size
SEGMENT_SIZE = COMMAND_FORMAT.size + STATUS_FORMAT.size


@dataclass(frozen=True)
class HookStatus:
    acknowledged_sequence: int
    state: int
    error_code: int
    simulation_time_us: int
    heartbeat_monotonic_ns: int
    generation: int


def encode_command(
    sequence: int,
    experiment_id: int,
    drift: EffectiveDrift | None,
    *,
    published_monotonic_ns: int | None = None,
    ttl_ns: int = 2_000_000_000,
) -> bytes:
    """Serialize a command; ``drift=None`` creates an explicit disable."""
    if sequence <= 0 or experiment_id < 0:
        raise ValueError("sequence must be positive and experiment_id non-negative")
    if ttl_ns <= 0:
        raise ValueError("ttl_ns must be positive")
    published = time.monotonic_ns() if published_monotonic_ns is None else published_monotonic_ns
    if drift is None:
        flags, mode, delay_us, speed, bearing = 0, MODE_COHERENT, 0, 0.0, 0.0
    else:
        flags = FLAG_ACTIVE
        mode = MODE_COHERENT if drift.mode is DriftMode.COHERENT else MODE_POSITION_ONLY
        delay_us = round(drift.start_delay_s * 1_000_000)
        speed = drift.horizontal_speed_mps
        bearing = drift.bearing_deg
        if delay_us < 0 or not math.isfinite(speed) or speed < 0:
            raise ValueError("invalid delay or horizontal speed")
        if not math.isfinite(bearing) or not 0 <= bearing <= 360:
            raise ValueError("bearing must be finite and within 0..360 degrees")
    return COMMAND_FORMAT.pack(
        WIRE_MAGIC, WIRE_VERSION, COMMAND_FORMAT.size, sequence, experiment_id,
        flags, mode, delay_us, speed, bearing, published, ttl_ns,
    )


def decode_status(data: bytes) -> HookStatus:
    if len(data) != STATUS_FORMAT.size:
        raise ValueError("status block has incorrect size")
    magic, version, size, ack, state, error, sim_us, heartbeat, generation = STATUS_FORMAT.unpack(data)
    if magic != WIRE_MAGIC or version != WIRE_VERSION or size != STATUS_FORMAT.size:
        raise ValueError("status block has invalid magic, version, or size")
    return HookStatus(ack, state, error, sim_us, heartbeat, generation)


class SystemVGPSBlock:
    """Attach to the GPS command/status segment using the Python standard library."""

    IPC_CREAT = 0o1000
    IPC_EXCL = 0o2000
    IPC_RMID = 0

    def __init__(self, key: int = GPS_SHM_KEY, *, create: bool = True):
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
        self._libc.shmget.restype = ctypes.c_int
        self._libc.shmat.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self._libc.shmat.restype = ctypes.c_void_p
        self._libc.shmdt.argtypes = [ctypes.c_void_p]
        self._libc.shmdt.restype = ctypes.c_int
        self._libc.shmctl.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        self._libc.shmctl.restype = ctypes.c_int
        flags = 0o666 | (self.IPC_CREAT | self.IPC_EXCL if create else 0)
        self._shmid = self._libc.shmget(key, SEGMENT_SIZE, flags)
        created = self._shmid >= 0
        if self._shmid < 0 and create and ctypes.get_errno() == 17:  # EEXIST
            self._shmid = self._libc.shmget(key, SEGMENT_SIZE, 0o666)
        if self._shmid < 0:
            self._raise_errno("shmget")
        address = self._libc.shmat(self._shmid, None, 0)
        if address == ctypes.c_void_p(-1).value:
            self._raise_errno("shmat")
        self._address = address
        if created:
            ctypes.memset(self._address, 0, SEGMENT_SIZE)
            self.write_status(STATUS_FORMAT.pack(
                WIRE_MAGIC, WIRE_VERSION, STATUS_FORMAT.size, 0,
                STATE_STARTING, 0, 0, 0, 0,
            ))

    @staticmethod
    def _raise_errno(operation: str) -> None:
        err = ctypes.get_errno()
        raise OSError(err, f"{operation} failed: {os.strerror(err)}")

    def write_command(self, data: bytes) -> None:
        if len(data) != COMMAND_FORMAT.size:
            raise ValueError("command block has incorrect size")
        ctypes.memmove(self._address, data, len(data))

    def read_command(self) -> bytes:
        return ctypes.string_at(self._address, COMMAND_FORMAT.size)

    def write_status(self, data: bytes) -> None:
        if len(data) != STATUS_FORMAT.size:
            raise ValueError("status block has incorrect size")
        ctypes.memmove(self._address + STATUS_OFFSET, data, len(data))

    def read_status(self) -> HookStatus:
        data = ctypes.string_at(self._address + STATUS_OFFSET, STATUS_FORMAT.size)
        return decode_status(data)

    def is_ready(self, expected_sequence: int) -> bool:
        status = self.read_status()
        return status.state == STATE_READY and status.acknowledged_sequence == expected_sequence

    def is_fresh(self, *, now_monotonic_ns: int | None = None, max_age_ns: int = 2_000_000_000) -> bool:
        status = self.read_status()
        now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        return (
            status.state == STATE_READY
            and status.heartbeat_monotonic_ns > 0
            and 0 <= now - status.heartbeat_monotonic_ns <= max_age_ns
        )

    def disable(self, sequence: int, experiment_id: int) -> None:
        self.write_command(encode_command(sequence, experiment_id, None))

    def close(self, *, remove: bool = False) -> None:
        address = getattr(self, "_address", None)
        if address is not None:
            self._libc.shmdt(ctypes.c_void_p(address))
            del self._address
        if remove and getattr(self, "_shmid", -1) >= 0:
            if self._libc.shmctl(self._shmid, self.IPC_RMID, None) != 0:
                self._raise_errno("shmctl(IPC_RMID)")
            self._shmid = -1

    def __enter__(self) -> "SystemVGPSBlock":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
