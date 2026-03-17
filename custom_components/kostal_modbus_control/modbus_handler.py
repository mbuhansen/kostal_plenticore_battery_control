import logging
import struct
import asyncio

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder
from pymodbus.constants import Endian

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
                self._client = AsyncModbusTcpClient(self._host, port=self._port)
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
        """Invoke read_holding_registers with compatible unit/slave argument."""
        # Try 'slave' first (v3+ standard) and force count as kwarg just in case
        try:
            return await self._client.read_holding_registers(
                address=address, count=count, slave=self._unit_id
            )
        except TypeError:
            # Fallback to 'unit' (older versions)
            try:
                return await self._client.read_holding_registers(
                    address=address, count=count, unit=self._unit_id
                )
            except TypeError:
                # Fallback to no unit/slave, only address and count
                try:
                    return await self._client.read_holding_registers(
                        address, count=count
                    )
                except TypeError:
                     # Absolute last resort: maybe count is positional really?
                     # Or maybe method name is different? but error said read_holding_registers
                     self._logger.error("Could not call read_holding_registers. Signature mismatch.")
                     raise

    async def _safe_write(self, address, values):
        """Invoke write_registers with compatible unit/slave argument."""
        try:
            return await self._client.write_registers(
                address=address, values=values, slave=self._unit_id
            )
        except TypeError:
            try:
                return await self._client.write_registers(
                    address=address, values=values, unit=self._unit_id
                )
            except TypeError:
                return await self._client.write_registers(
                    address=address, values=values
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
                
                # Kostal typically uses Big Endian Byte order, and Big Endian Word order for strings
                # But if 'swap: word' is active for floats, we must be careful.
                # Usually strings are just a stream of bytes.
                decoder = BinaryPayloadDecoder.fromRegisters(
                    result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
                )
                # Decode string and strip null bytes
                decoded = decoder.decode_string(length * 2).decode("utf-8").strip('\x00')
                return decoded
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
                
                # 'swap: word' implies Little Endian Word Order with Big Endian Byte Order
                decoder = BinaryPayloadDecoder.fromRegisters(
                    result.registers, byteorder=Endian.BIG, wordorder=Endian.LITTLE
                )
                val = decoder.decode_32bit_float()
                return val
            except Exception as e:
                self._logger.error(f"Exception reading float from {address}: {e}")
                return None

    async def write_float(self, address, value):
        """Writes a float value to two 16-bit registers."""
        await self.connect()
        # 'swap: word' implies Little Endian Word Order with Big Endian Byte Order
        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE)
        builder.add_32bit_float(float(value))
        registers = builder.to_registers()
        
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
