"""Minimal GGUF header probe: read ONLY the metadata KV section.

Why: GGUFReader tries to mmap tensor payloads. When we probe a truncated file
(partial download) that blows up. This reads just magic + version + counts +
KV pairs, which is enough to check whether a remote GGUF is compatible with
our llama.cpp build before spending 3 GB of bandwidth.
"""

import struct
import sys

# GGUF value types
U8, I8, U16, I16, U32, I32, F32, BOOL, STR, ARR, U64, I64, F64 = range(13)

SCALAR_FMT = {
    U8: ("<B", 1), I8: ("<b", 1), U16: ("<H", 2), I16: ("<h", 2),
    U32: ("<I", 4), I32: ("<i", 4), F32: ("<f", 4), BOOL: ("<?", 1),
    U64: ("<Q", 8), I64: ("<q", 8), F64: ("<d", 8),
}


def _read_str(f):
    (ln,) = struct.unpack("<Q", f.read(8))
    return f.read(ln).decode("utf-8", errors="replace")


def _read_value(f, vtype):
    if vtype == STR:
        return _read_str(f)
    if vtype == ARR:
        (elem,) = struct.unpack("<I", f.read(4))
        (count,) = struct.unpack("<Q", f.read(8))
        vals = [_read_value(f, elem) for _ in range(count)]
        return vals
    if vtype in SCALAR_FMT:
        fmt, size = SCALAR_FMT[vtype]
        return struct.unpack(fmt, f.read(size))[0]
    raise ValueError(f"unknown gguf value type {vtype}")


def probe(path, verbose=False):
    out = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return {"error": "not a GGUF file"}
        ver = struct.unpack("<I", f.read(4))[0]
        (tensor_count,) = struct.unpack("<Q", f.read(8))[0:1]
        (kv_count,) = struct.unpack("<Q", f.read(8))[0:1]
        out["gguf_version"] = ver
        out["tensor_count"] = tensor_count
        out["kv_count"] = kv_count

        for _ in range(kv_count):
            try:
                key = _read_str(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                val = _read_value(f, vtype)
            except Exception as e:
                out["truncated_at"] = key if "key" in dir() else "?"
                break
            out[key] = val
            if verbose:
                print(f"  {key} = {val}")
    return out


if __name__ == "__main__":
    p = sys.argv[1]
    info = probe(p, verbose="-v" in sys.argv)
    if "error" in info:
        print(info["error"])
        sys.exit(1)
    print(f"GGUF v{info['gguf_version']}  tensors={info['tensor_count']}  kv={info['kv_count']}")
    if "truncated_at" in info:
        print(f"(metadata truncated after {info['truncated_at']})")
    print("\n--- rope / mrope related ---")
    for k, v in info.items():
        if isinstance(k, str) and ("rope" in k or "section" in k or "mrope" in k):
            n = len(v) if isinstance(v, list) else "-"
            print(f"  {k}: len={n} value={v if not isinstance(v, list) or len(v) <= 8 else v[:8]}")
