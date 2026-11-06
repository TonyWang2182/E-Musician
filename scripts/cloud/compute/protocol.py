"""Small standard-library request contract shared by server and isolated workers."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import struct

VERSION = 2
MAX_BODY = 32768
MAX_ASSET = 512 * 1024**2
MAX_RESULT = 16 * 1024**2
TERMINAL = frozenset({'ready', 'failed', 'cancelled', 'interrupted'})
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
SPECS = {
    'ace-step-1.5-xl-turbo': {'kind': 'generate', 'env': 'ace', 'limit': 120, 'timeout': 900, 'gpu_gib': 22},
    'yue2': {'kind': 'generate', 'env': 'yue2', 'limit': 120, 'timeout': 1200, 'gpu_gib': 12},
    'scnet': {'kind': 'separate', 'env': 'scnet', 'limit': 600, 'timeout': 1800, 'gpu_gib': 8},
    'transkun': {'kind': 'transcribe', 'env': 'transkun', 'limit': 600, 'timeout': 1800, 'gpu_gib': 8},
    'chordmini': {'kind': 'chords', 'env': 'chordmini', 'limit': 600, 'timeout': 1800, 'gpu_gib': 8},
    'muscriptor': {'kind': 'transcribe', 'env': 'muscriptor', 'limit': 600, 'timeout': 1800, 'gpu_gib': 10},
    'sheetsage2': {'kind': 'score', 'env': 'sheetsage2', 'limit': 600, 'timeout': 1800, 'gpu_gib': 12},
}


def number(value, low, high):
    if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Number outside supported range')
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('Invalid request identifier')
    return value


def sha256(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError('Invalid SHA-256')
    return value


def text(value, maximum, minimum=0):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValueError('Text outside supported range')
    return value


def validate_request(value):
    if not isinstance(value, dict) or set(value) - {'request_id', 'kind', 'model_id', 'input', 'parameters'}:
        raise ValueError('Unknown request fields')
    request_id = identifier(value.get('request_id'))
    model = value.get('model_id')
    if not isinstance(model, str) or model not in SPECS or value.get('kind') != SPECS[model]['kind']:
        raise ValueError('Unsupported model/task combination')
    parameters = value.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('Parameters must be an object')
    result = {'request_id': request_id, 'kind': value['kind'], 'model_id': model, 'parameters': {}}
    if value['kind'] == 'generate':
        if 'input' in value or set(parameters) != {'prompt', 'lyrics', 'instrumental', 'duration_seconds', 'bpm', 'time_signature', 'seed'}:
            raise ValueError('Generation requires exactly the documented conditioning fields')
        p = dict(parameters)
        text(p['prompt'], 2000, 1); text(p['lyrics'], 4096)
        if type(p['instrumental']) is not bool or (p['instrumental'] and p['lyrics'].strip()):
            raise ValueError('Instrumental jobs must have empty lyrics')
        number(p['duration_seconds'], 10, 120); number(p['bpm'], 30, 300)
        if p['time_signature'] not in ('2/4', '3/4', '4/4', '6/8'):
            raise ValueError('Unsupported time signature')
        if type(p['seed']) is not int or not 0 <= p['seed'] <= 2**31 - 1:
            raise ValueError('Seed must be a 31-bit nonnegative integer')
        result['parameters'] = p
    else:
        if parameters:
            raise ValueError('These pinned cloud MIR models currently use their documented fixed inference settings')
        source = value.get('input')
        if not isinstance(source, dict) or set(source) != {'sha256'}:
            raise ValueError('Analysis requires a previously uploaded content-addressed WAV')
        result['input'] = {'sha256': sha256(source['sha256'])}
    return result


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_json(path, limit=MAX_RESULT):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('JSON exceeds size budget')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(canonical(value) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def wav_info(path):
    """Validate bounded RIFF PCM16/FLOAT32 without importing audio/model libraries."""
    path = Path(path); size = path.stat().st_size
    if not 44 <= size <= MAX_ASSET:
        raise ValueError('WAV byte size outside budget')
    fmt = data = None
    with path.open('rb') as stream:
        header = stream.read(12)
        if header[:4] != b'RIFF' or header[8:] != b'WAVE' or struct.unpack('<I', header[4:8])[0] + 8 != size:
            raise ValueError('Only complete RIFF WAVE assets are supported')
        chunks = 0
        while stream.tell() + 8 <= size:
            chunks += 1
            if chunks > 128:
                raise ValueError('Too many WAV chunks')
            name, length = struct.unpack('<4sI', stream.read(8))
            position = stream.tell()
            if position + length + (length & 1) > size:
                raise ValueError('Truncated WAV chunk')
            if name == b'fmt ':
                if fmt is not None or length < 16 or length > 128:
                    raise ValueError('Invalid WAV format chunk')
                fmt = struct.unpack('<HHIIHH', stream.read(16))
            elif name == b'data':
                if data is not None:
                    raise ValueError('Multiple WAV data chunks are unsupported')
                data = length
            stream.seek(position + length + (length & 1))
    if fmt is None or data is None:
        raise ValueError('WAV is missing format or data')
    encoding, channels, rate, byte_rate, alignment, bits = fmt
    if (encoding, bits) not in ((1, 16), (3, 32)) or channels not in (1, 2) or not 8000 <= rate <= 96000:
        raise ValueError('Use mono/stereo PCM16 or FLOAT32 WAV at 8–96 kHz')
    if alignment != channels * bits // 8 or byte_rate != rate * alignment or data % alignment:
        raise ValueError('WAV block geometry is invalid')
    frames = data // alignment
    if not 0 < frames / rate <= 600:
        raise ValueError('WAV duration must be greater than zero and at most 600 seconds')
    return {'bytes': size, 'frames': frames, 'sample_rate': rate, 'channels': channels,
            'sample_format': 'pcm16' if encoding == 1 else 'float32', 'duration_seconds': frames / rate}
