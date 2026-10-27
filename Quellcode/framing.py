"""Sicherer JSON-Lines-Parser für TLS-geschützte RPC-Verbindungen."""
import json

MAX_LINE = 65536
MAX_BUFFER = 131072


class JsonLines:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        if len(self.buffer) > MAX_BUFFER:
            raise ValueError('Receive buffer too large')
        if len(self.buffer) > MAX_LINE and b'\n' not in self.buffer:
            raise ValueError('JSON line too large')
        messages = []
        while b'\n' in self.buffer:
            idx = self.buffer.index(10)
            line = bytes(self.buffer[:idx])
            del self.buffer[:idx + 1]
            if len(line) > MAX_LINE:
                raise ValueError('JSON line too large')
            if not line:
                continue
            item = json.loads(line.decode('utf-8'))
            if not isinstance(item, dict):
                raise ValueError('JSON RPC message must be an object')
            messages.append(item)
        return messages


def encode_message(message):
    if not isinstance(message, dict):
        raise TypeError('Expected JSON object')
    data = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
    if len(data) > MAX_LINE:
        raise ValueError('JSON line too large')
    return data
