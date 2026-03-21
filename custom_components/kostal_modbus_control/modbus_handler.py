import logging
import struct
import asyncio
import inspect
from pymodbus.client import AsyncModbusTcpClient

class KostalModbusHandler:
    def __init__(self, host, port, unit_id):
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client = None
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)
        self._unit_kwarg = None  # Detected at first use

    async def _ensure_connected(self):
        """Ensure Modbus client is connected. Must be called while holding self._lock."""
        if not self._client:
            self._client = AsyncModbusTcpClient(self._host, port=self._port, timeout=10)
        if not self._client.connected:
            connected = await self._client.connect()
            if not connected:
                raise ConnectionError("Failed to connect to Modbus host %s:%s" % (self._host, self._port))

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
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, length)
                
                if result.isError():
                    self._logger.error("Error reading string from %s: %s", address, result)
                    return None
                
                # Build raw bytes from registers (Big Endian byte and word order)
                raw = b"".join(struct.pack(">H", r) for r in result.registers)
                return raw.decode("utf-8", errors="replace").strip("\x00")
            except Exception as e:
                self._logger.error("Exception reading string from %s: %s", address, e)
                return None

    async def read_float(self, address):
        """Reads a float (32-bit) from two 16-bit registers."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, 2)
                if result.isError():
                    self._logger.error("Error reading float from %s: %s", address, result)
                    return None
                # Big Endian bytes, Little Endian word order: [low_word, high_word]
                raw = struct.pack(">HH", result.registers[1], result.registers[0])
                return struct.unpack(">f", raw)[0]
            except Exception as e:
                self._logger.error("Exception reading float from %s: %s", address, e)
                return None

    async def read_int16(self, address):
        """Reads a signed 16-bit integer from one register."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, 1)
                if result.isError():
                    self._logger.error("Error reading int16 from %s: %s", address, result)
                    return None
                raw = struct.pack(">H", result.registers[0])
                return struct.unpack(">h", raw)[0]
            except Exception as e:
                self._logger.error("Exception reading int16 from %s: %s", address, e)
                return None

    async def read_uint8(self, address):
        """Reads an unsigned 8-bit value from the low byte of one register."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, 1)
                if result.isError():
                    self._logger.error("Error reading uint8 from %s: %s", address, result)
                    return None
                return result.registers[0] & 0xFF
            except Exception as e:
                self._logger.error("Exception reading uint8 from %s: %s", address, e)
                return None

    async def read_uint16(self, address):
        """Reads an unsigned 16-bit value from one register."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, 1)
                if result.isError():
                    self._logger.error("Error reading uint16 from %s: %s", address, result)
                    return None
                return result.registers[0]
            except Exception as e:
                self._logger.error("Exception reading uint16 from %s: %s", address, e)
                return None

    async def read_uint32(self, address):
        """Reads an unsigned 32-bit value from two 16-bit registers (big endian)."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_read(address, 2)
                if result.isError():
                    self._logger.error("Error reading uint32 from %s: %s", address, result)
                    return None
                raw = struct.pack(">HH", result.registers[0], result.registers[1])
                return struct.unpack(">I", raw)[0]
            except Exception as e:
                self._logger.error("Exception reading uint32 from %s: %s", address, e)
                return None

    async def write_float(self, address, value):
        """Writes a float value to two 16-bit registers."""
        # Big Endian bytes, Little Endian word order: write [low_word, high_word]
        raw = struct.pack(">f", float(value))
        high_word, low_word = struct.unpack(">HH", raw)
        registers = [low_word, high_word]
        
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_write(address, registers)
                
                if result.isError():
                    self._logger.error("Error writing to %s: %s", address, result)
            except Exception as e:
                self._logger.error("Exception writing to %s: %s", address, e)
                # Force reconnect on next attempt
                self._close_unlocked()

    async def write_registers(self, address, values):
        """Writes raw register values."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_write(address, values)
                
                if result.isError():
                    self._logger.error("Error writing to %s: %s", address, result)
            except Exception as e:
                self._logger.error("Exception writing to %s: %s", address, e)
                self._close_unlocked()

    async def write_register(self, address, value):
        """Writes a single 16-bit register using Modbus function 0x06."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await self._safe_write_single(address, value)

                if result.isError():
                    self._logger.error("Error writing single register to %s: %s", address, result)
            except Exception as e:
                self._logger.error("Exception writing single register to %s: %s", address, e)
                self._close_unlocked()
