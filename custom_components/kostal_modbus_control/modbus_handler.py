import logging
import struct
import asyncio

from pymodbus.client import AsyncModbusTcpClient

class KostalModbusHandler:
    def __init__(self, host, port, unit_id):
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client = None
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)

    async def connect(self):
        async with self._lock:
            if not self._client:
                self._client = AsyncModbusTcpClient(self._host, port=self._port, timeout=10)
            if not self._client.connected:
                connected = await self._client.connect()
                if not connected:
                    raise ConnectionError(f"Failed to connect to Modbus host {self._host}:{self._port}")

    async def close(self):
        async with self._lock:
            if self._client:
                self._client.close()
                self._client = None
    
    async def _safe_read(self, address, count):
        """Read holding registers using pymodbus 3.6+ API."""
        self._logger.debug("READ address=%s count=%s slave=%s", address, count, self._unit_id)
        return await self._client.read_holding_registers(
            address=address, count=count, slave=self._unit_id
        )

    async def _safe_write(self, address, values):
        """Write registers using pymodbus 3.6+ API."""
        self._logger.debug("WRITE address=%s values=%s slave=%s", address, values, self._unit_id)
        return await self._client.write_registers(
            address=address, values=values, slave=self._unit_id
        )

    async def read_string(self, address, length):
        """Reads a string from holding registers."""
        # length is the number of registers to read.
        # Typically 1 register = 2 characters (bytes).
        await self.connect()
        async with self._lock:
            try:
                # Use internal safe wrapper
                result = await self._safe_read(address, length)
                
                if result.isError():
                    self._logger.error(f"Error reading string from {address}: {result}")
                    return None
                
                # Build raw bytes from registers (Big Endian byte and word order)
                raw = b"".join(struct.pack(">H", r) for r in result.registers)
                return raw.decode("utf-8", errors="replace").strip("\x00")
            except Exception as e:
                self._logger.error(f"Exception reading string from {address}: {e}")
                return None

    async def read_float(self, address):
        """Reads a float (32-bit) from two 16-bit registers."""
        # Based on user config 'swap: word', we need Little Endian Word Order.
        await self.connect()
        async with self._lock:
            try:
                # Use internal safe wrapper
                result = await self._safe_read(address, 2)
                
                if result.isError():
                    self._logger.error(f"Error reading float from {address}: {result}")
                    return None
                
                # Big Endian bytes, Little Endian word order: [low_word, high_word]
                raw = struct.pack(">HH", result.registers[1], result.registers[0])
                return struct.unpack(">f", raw)[0]
            except Exception as e:
                self._logger.error(f"Exception reading float from {address}: {e}")
                return None

    async def write_float(self, address, value):
        """Writes a float value to two 16-bit registers."""
        await self.connect()
        # Big Endian bytes, Little Endian word order: write [low_word, high_word]
        raw = struct.pack(">f", float(value))
        high_word, low_word = struct.unpack(">HH", raw)
        registers = [low_word, high_word]
        
        async with self._lock:
            try:
                # Use internal safe wrapper
                result = await self._safe_write(address, registers)
                
                if result.isError():
                    self._logger.error(f"Error writing to {address}: {result}")
            except Exception as e:
                self._logger.error(f"Exception writing to {address}: {e}")
                # Force reconnect on next attempt
                await self.close()

    async def write_registers(self, address, values):
        """Writes raw register values."""
        await self.connect()
        async with self._lock:
            try:
                # Use internal safe wrapper
                result = await self._safe_write(address, values)
                
                if result.isError():
                    self._logger.error(f"Error writing to {address}: {result}")
            except Exception as e:
                self._logger.error(f"Exception writing to {address}: {e}")
                await self.close()
