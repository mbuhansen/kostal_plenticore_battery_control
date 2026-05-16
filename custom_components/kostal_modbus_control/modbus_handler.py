import logging
import struct
import asyncio
import inspect
from pymodbus.client import AsyncModbusTcpClient


class KostalModbusError(Exception):
    """Base exception for Modbus operation failures."""


class KostalModbusConnectionError(KostalModbusError):
    """Raised when a Modbus operation cannot complete reliably."""

class KostalModbusHandler:
    def __init__(self, host, port, unit_id):
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client = None
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)
        self._unit_kwarg = None  # Detected at first use
        self._operation_timeout = 15.0
        self._word_swapped_32bit = True

    def set_modbus_byte_order(self, byte_order):
        """Apply inverter Modbus byte-order setting for 32-bit values."""
        if byte_order == 0x00:
            self._word_swapped_32bit = True
            self._logger.info("Using inverter Modbus byte order: little-endian (CDAB)")
            return

        if byte_order == 0x01:
            self._word_swapped_32bit = False
            self._logger.info("Using inverter Modbus byte order: big-endian (ABCD)")
            return

        self._logger.warning(
            "Unknown inverter Modbus byte order value %s; keeping %s 32-bit word order",
            byte_order,
            "swapped" if self._word_swapped_32bit else "normal",
        )

    def _register_words_to_bytes(self, first_word, second_word):
        """Build 32-bit raw bytes from two Modbus registers using configured word order."""
        if self._word_swapped_32bit:
            return struct.pack(">HH", second_word, first_word)
        return struct.pack(">HH", first_word, second_word)

    def _float_to_register_words(self, value):
        """Encode a float into two Modbus registers using configured word order."""
        raw = struct.pack(">f", float(value))
        high_word, low_word = struct.unpack(">HH", raw)
        if self._word_swapped_32bit:
            return [low_word, high_word]
        return [high_word, low_word]

    async def _ensure_connected(self):
        """Ensure Modbus client is connected. Must be called while holding self._lock."""
        if not self._client:
            self._client = AsyncModbusTcpClient(self._host, port=self._port, timeout=10)
        if not self._client.connected:
            connected = await self._client.connect()
            if not connected:
                raise KostalModbusConnectionError("Failed to connect to Modbus host %s:%s" % (self._host, self._port))

    async def connect(self):
        """Public connect — acquires lock. Used by config_flow and initial setup."""
        async with self._lock:
            await self._ensure_connected()

    async def close(self):
        async with self._lock:
            self._close_unlocked()

    def _close_unlocked(self):
        """Close without acquiring lock. Must be called while holding self._lock."""
        if self._client:
            self._client.close()
            self._client = None

    async def _run_locked_request(self, description, operation):
        """Run a Modbus request under the shared lock with timeout and teardown."""
        async with self._lock:
            try:
                await asyncio.wait_for(self._ensure_connected(), timeout=self._operation_timeout)
                result = await asyncio.wait_for(operation(), timeout=self._operation_timeout)
            except asyncio.TimeoutError as err:
                self._logger.warning("Timeout during %s", description)
                self._close_unlocked()
                raise KostalModbusConnectionError(f"Timeout during {description}") from err
            except Exception as err:
                self._logger.warning("Transport error during %s: %s", description, err)
                self._close_unlocked()
                raise KostalModbusConnectionError(f"{description} failed: {err}") from err

            if result.isError():
                self._logger.warning("Modbus error during %s: %s", description, result)
                self._close_unlocked()
                raise KostalModbusConnectionError(f"{description} failed: {result}")

            return result

    def _detect_unit_kwarg(self):
        """Detect the parameter name for slave/unit ID in this pymodbus version."""
        if self._unit_kwarg is not None:
            return
        params = inspect.signature(self._client.read_holding_registers).parameters
        self._logger.debug("pymodbus read_holding_registers params: %s", list(params.keys()))
        for name in ("slave", "unit", "dev_id", "device_id"):
            if name in params:
                self._unit_kwarg = name
                self._logger.debug("Using '%s' as unit_id kwarg", name)
                return
        self._unit_kwarg = ""  # No unit kwarg found
        self._logger.warning("No unit/slave/dev_id param found — unit_id will NOT be sent!")

    async def _safe_read(self, address, count):
        """Read holding registers with auto-detected unit_id parameter name."""
        self._detect_unit_kwarg()
        kwargs = {"count": count}
        if self._unit_kwarg:
            kwargs[self._unit_kwarg] = self._unit_id
        return await self._client.read_holding_registers(address, **kwargs)

    async def _safe_write(self, address, values):
        """Write registers with auto-detected unit_id parameter name."""
        self._detect_unit_kwarg()
        kwargs = {"values": values}
        if self._unit_kwarg:
            kwargs[self._unit_kwarg] = self._unit_id
        return await self._client.write_registers(address, **kwargs)

    async def _safe_write_single(self, address, value):
        """Write a single register with auto-detected unit_id parameter name."""
        self._detect_unit_kwarg()
        kwargs = {"value": value}
        if self._unit_kwarg:
            kwargs[self._unit_kwarg] = self._unit_id
        return await self._client.write_register(address, **kwargs)

    async def read_string(self, address, length):
        """Reads a string from holding registers."""
        result = await self._run_locked_request(
            f"read string from {address}",
            lambda: self._safe_read(address, length),
        )

        raw = b"".join(struct.pack(">H", r) for r in result.registers)
        return raw.decode("utf-8", errors="replace").strip("\x00")

    async def read_float(self, address):
        """Reads a float (32-bit) from two 16-bit registers."""
        result = await self._run_locked_request(
            f"read float from {address}",
            lambda: self._safe_read(address, 2),
        )
        raw = self._register_words_to_bytes(result.registers[0], result.registers[1])
        return struct.unpack(">f", raw)[0]

    async def read_int16(self, address):
        """Reads a signed 16-bit integer from one register."""
        result = await self._run_locked_request(
            f"read int16 from {address}",
            lambda: self._safe_read(address, 1),
        )
        raw = struct.pack(">H", result.registers[0])
        return struct.unpack(">h", raw)[0]

    async def read_uint8(self, address):
        """Reads an unsigned 8-bit value from the low byte of one register."""
        result = await self._run_locked_request(
            f"read uint8 from {address}",
            lambda: self._safe_read(address, 1),
        )
        return result.registers[0] & 0xFF

    async def read_uint16(self, address):
        """Reads an unsigned 16-bit value from one register."""
        result = await self._run_locked_request(
            f"read uint16 from {address}",
            lambda: self._safe_read(address, 1),
        )
        return result.registers[0]

    async def read_int32(self, address):
        """Reads a signed 32-bit value from two 16-bit registers using configured word order."""
        result = await self._run_locked_request(
            f"read int32 from {address}",
            lambda: self._safe_read(address, 2),
        )
        raw = self._register_words_to_bytes(result.registers[0], result.registers[1])
        return struct.unpack(">i", raw)[0]

    async def read_uint32(self, address):
        """Reads an unsigned 32-bit value from two 16-bit registers using configured word order."""
        result = await self._run_locked_request(
            f"read uint32 from {address}",
            lambda: self._safe_read(address, 2),
        )
        raw = self._register_words_to_bytes(result.registers[0], result.registers[1])
        return struct.unpack(">I", raw)[0]

    async def read_int64(self, address):
        """Reads a signed 64-bit integer from four 16-bit registers (big-endian ABCDEFGH)."""
        result = await self._run_locked_request(
            f"read int64 from {address}",
            lambda: self._safe_read(address, 4),
        )
        raw = struct.pack(">HHHH", *result.registers)
        return struct.unpack(">q", raw)[0]

    async def write_float(self, address, value):
        """Writes a float value to two 16-bit registers."""
        registers = self._float_to_register_words(value)
        
        await self._run_locked_request(
            f"write float to {address}",
            lambda: self._safe_write(address, registers),
        )

    async def write_registers(self, address, values):
        """Writes raw register values."""
        await self._run_locked_request(
            f"write registers to {address}",
            lambda: self._safe_write(address, values),
        )

    async def write_register(self, address, value):
        """Writes a single 16-bit register using Modbus function 0x06."""
        await self._run_locked_request(
            f"write single register to {address}",
            lambda: self._safe_write_single(address, value),
        )
