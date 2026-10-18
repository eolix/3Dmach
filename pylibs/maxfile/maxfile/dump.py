# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
``maxdump``: print what :mod:`maxfile` sees in a ``.max`` file.

Usage::

    python -m maxfile.dump scene.max                        # summary: streams, classes, node tree, unknowns
    python -m maxfile.dump scene.max --chunks               # chunk tree of every scene object
    python -m maxfile.dump scene.max --chunks --object 12 --depth 2
    python -m maxfile.dump scene.max --stream ClassDirectory3
    python -m maxfile.dump scene.max --object 12 --decode   # what the decoders make of object 12
    python -m maxfile.dump scene.max --json                 # any of the above as JSON

Output is meant to be grepped: scene objects are written ``[12]``, class-directory entries ``#5``, chunk types
``0x0962``, and details as ``key=value``. See ``docs/format/maxdump.md``.
"""

__all__ = (
    "main",
    "summary",
    "chunk_rows",
    "decoded_object",
)

import argparse
import json
import math
import os
import sys

import maxfile

from . import chunks as _chunks
from . import registry, report
from .objects.geometry import MeshData
from .objects.materials import MaterialData
from .objects.modifiers import ModifierStack
from .objects.primitives import PrimitiveData
from .scene import SCENE_STREAM
from .transform import Transform

DEFAULT_PREVIEW = 16


# -----------------------------------------------------------------------------
# Formatting helpers

def _num(value: float) -> str:
    return "{:.6g}".format(value)


def _json_safe(value):
    """Replace non-finite floats (not valid JSON) by strings; the data passed in is only a few levels deep."""
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _write_json(data, out):
    json.dump(_json_safe(data), out, indent=1, ensure_ascii=False, allow_nan=False)
    out.write("\n")


def _vec(values) -> str:
    return "(" + ", ".join(_num(v) for v in values) + ")"


def _u32_text(value: int) -> str:
    """Small values in decimal (counts, indices), large ones in hex (flags, IDs, 0xFFFFFFFF)."""
    return str(value) if value < 0x10000 else "0x{:08X}".format(value)


def _hex(data: bytes, limit: int) -> str:
    text = " ".join("{:02X}".format(b) for b in data[:limit])
    return text + (" ..." if len(data) > limit else "")


def _text_preview(data: bytes) -> str | None:
    """The payload as text when it plausibly is UTF-16LE text, else None."""
    if len(data) < 2 or len(data) % 2:
        return None
    try:
        text = data.decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    text = text.rstrip("\0")
    if not text or "\0" in text or not text.isprintable():
        return None
    # Short binary values often decode to printable CJK characters; require mostly-ASCII text.
    ascii_count = sum(1 for c in text if " " <= c <= "~")
    if ascii_count * 2 < len(text):
        return None
    return text


def _transform_json(t: Transform | None):
    if t is None:
        return None
    return {"position": t.position, "rotation_wxyz": t.rotation, "scale": t.scale}


def _transform_text(t: Transform | None, prefix: str) -> str:
    if t is None:
        return ""
    parts = []
    if t.position is not None:
        parts.append("{:s}pos={:s}".format(prefix, _vec(t.position)))
    if t.rotation is not None and t.rotation != (1.0, 0.0, 0.0, 0.0):
        parts.append("{:s}rot_wxyz={:s}".format(prefix, _vec(t.rotation)))
    if t.scale is not None and t.scale != (1.0, 1.0, 1.0):
        parts.append("{:s}scale={:s}".format(prefix, _vec(t.scale)))
    return "  ".join(parts)


def _obj_ref(obj):
    if obj is None:
        return None
    return {"index": obj.index, "class_index": obj.class_index, "class": obj.class_label()}


def _obj_ref_text(obj) -> str:
    return "[{:d}] {:s}".format(obj.index, obj.class_label())


def _hex32(value) -> str | None:
    return None if value is None else "0x{:08X}".format(value)


# -----------------------------------------------------------------------------
# Summary

def summary(mf: "maxfile.MaxFile") -> dict:
    """Everything the default output shows, as JSON-compatible data."""
    container = mf.container
    data = {
        "file": mf.path,
        "container": {
            "version": container.version,
            "sector_size": container.sector_size,
        },
    }

    streams = []
    for entry in mf.streams:
        info = {"path": entry.path_str, "stored_size": entry.size}
        try:
            stream = mf.stream(entry.path)
        except maxfile.MaxFileError as ex:
            info["error"] = str(ex)
        else:
            info.update(size=stream.size, compressed=stream.compressed, top_level_chunks=len(stream.chunks),
                        chunk_error=stream.error)
        streams.append(info)
    data["streams"] = streams

    usage = mf.class_usage()
    by_index = {u.entry.index: u for u in usage}
    classes = []
    for entry in mf.class_directory.entries:
        u = by_index[entry.index]
        classes.append({
            "index": entry.index,
            "name": entry.name,
            "class_id": str(entry.class_id) if entry.class_id is not None else None,
            "class_id_u64": entry.class_id.u64_str() if entry.class_id is not None else None,
            "superclass_id": _hex32(entry.superclass_id),
            "dll_index": entry.dll_index,
            "dll": entry.dll.label() if entry.dll is not None else None,
            "objects": u.count,
            "known": u.known.name if u.known else None,
            "category": u.known.category if u.known else None,
            "decoder": u.decoder.name if u.decoder else None,
            "error": entry.error,
        })
    data["class_directory"] = {"stream": mf.class_directory.stream_name, "classes": classes}
    data["dll_directory"] = [
        {"index": d.index, "strings": {"0x{:04X}".format(t): s for t, s in sorted(d.strings.items())}}
        for d in mf.dll_directory.entries
    ]

    scene = mf.scene
    data["objects"] = len(scene.objects)
    geometry = {node.index: scene.resolve_geometry(node) for node in scene.nodes}
    nodes = []
    # Depth-first from the roots, iteratively (parent cycles were broken when the scene was built).
    stack = [(0, node) for node in reversed(scene.roots)]
    while stack:
        depth, node = stack.pop()
        nodes.append({
            "index": node.index,
            "depth": depth,
            "name": node.name,
            "parent": node.parent.index if node.parent is not None else None,
            "parent_index": node.parent_index,
            "object": _obj_ref(node.object),
            "material": _obj_ref(node.material),
            "layer": _obj_ref(node.layer),
            "controller": _obj_ref(node.controller),
            "geometry": _obj_ref(geometry[node.index][0]),
            "modifiers": [_obj_ref(m) for m in geometry[node.index][1]],
            "transform": _transform_json(node.transform),
            "object_offset": _transform_json(node.object_offset),
        })
        stack.extend((depth + 1, child) for child in reversed(node.children))
    data["nodes"] = nodes
    data["roots"] = len(scene.roots)
    data.update(_decoded_sections(mf))

    data["unknown_classes"] = [
        {
            "index": u.entry.index,
            "name": u.entry.name,
            "class_id": str(u.entry.class_id) if u.entry.class_id is not None else None,
            "class_id_u64": u.entry.class_id.u64_str() if u.entry.class_id is not None else None,
            "superclass_id": _hex32(u.entry.superclass_id),
            "dll": u.entry.dll.label() if u.entry.dll is not None else None,
            "objects": u.count,
        }
        for u in mf.unknown_classes()
    ]
    data["undecoded"] = dict(scene.undecoded.most_common())
    data["warnings"] = mf.warnings
    return data


def _mesh_stats(mesh: MeshData | None):
    return None if mesh is None else dict(mesh.stats(), source=mesh.source, problems=len(mesh.warnings))


def _material_tree(mat: MaterialData, depth: int, rows: list, seen: set):
    """Flatten a material and its sub-materials into rows (iterative, each material once per tree)."""
    stack = [(depth, mat)]
    while stack:
        d, m = stack.pop()
        row = {
            "depth": d, "index": m.index, "class": m.class_name, "name": m.name,
            "params": report.to_plain(m.params),
            "maps": {k: _map_row(v) for k, v in m.maps.items()},
            "unassigned_maps": {str(slot): _map_row(v) for slot, v in m.unassigned_maps.items()},
            "sub_materials": None if m.sub_materials is None else len(m.sub_materials),
            "sub_ids": m.sub_ids,
            "param_blocks": m.param_blocks,
        }
        rows.append(row)
        if m.index in seen:
            row["repeated"] = True
            continue
        seen.add(m.index)
        for sub in reversed(m.sub_materials or []):
            if sub is not None:
                stack.append((d + 1, sub))


def _map_row(m):
    if m is None:
        return None
    return {"index": m.index, "class": m.class_name, "path": m.path, "path_source": m.path_source,
            "asset_index": m.asset_index}


def _decoded_sections(mf) -> dict:
    """Geometry, primitives, modifier stacks and materials, as decoded by the registered decoders."""
    scene = mf.scene
    geometry, primitives, stacks = [], [], []
    for obj in scene.objects:
        info = registry.find_decoder(obj.class_id, obj.superclass_id)
        if info is None or not info.kind.startswith("geometry."):
            continue
        value = scene.decode(obj)
        ref = _obj_ref(obj)
        if isinstance(value, MeshData):
            geometry.append(dict(ref, mesh=_mesh_stats(value)))
        elif isinstance(value, PrimitiveData):
            primitives.append(dict(ref, kind=value.kind, params=report.to_plain(value.params),
                                   encoding=value.encoding, extra_values=report.to_plain(value.extra_values),
                                   param_block=value.param_block, cached_mesh=_mesh_stats(value.cached_mesh)))
        elif isinstance(value, ModifierStack):
            stacks.append(dict(ref, base=_obj_ref(scene.objects[value.base]) if value.base is not None else None,
                               modifiers=[_obj_ref(scene.objects[m.object_index]) for m in value.modifiers]))
        else:
            geometry.append(dict(ref, mesh=None, error="not decoded (see warnings)"))
    materials = []
    seen = set()
    for node in scene.nodes:
        if node.material is None or node.material.index in seen:
            continue
        value = scene.decode(node.material)
        if isinstance(value, MaterialData):
            _material_tree(value, 0, materials, seen)
        else:
            seen.add(node.material.index)
            materials.append({"depth": 0, "index": node.material.index, "class": node.material.class_label(),
                              "decoded": False})
    return {"geometry": geometry, "primitives": primitives, "modifier_stacks": stacks, "materials": materials}


def _kv(params: dict) -> str:
    def value(v):
        # JSON-ready data has lists where the decoder had tuples; show vectors as tuples again.
        if isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
            v = tuple(v)
        return report.format_value(v)
    return "  ".join("{:s}={:s}".format(str(k), value(v)) for k, v in params.items())


def _mesh_text(stats) -> str:
    if stats is None:
        return "-"
    text = "vertices={:d} faces={:d} corners={:d} channels={:s} material_ids={:s} smoothing={:s}".format(
        stats["vertices"], stats["faces"], stats["corners"], ",".join(str(c) for c in stats["channels"]) or "-",
        ",".join(str(m) for m in stats["material_ids"][:16]) or "-", "yes" if stats["smoothing"] else "no")
    if stats["problems"]:
        text += " problems={:d}".format(stats["problems"])
    return text


def _ref_text(ref) -> str:
    return "-" if ref is None else "[{:d}] {:s}".format(ref["index"], ref["class"])


def _print_decoded(data: dict, w):
    w("\n== Geometry ({:d}) ==\n".format(len(data["geometry"])))
    for g in data["geometry"]:
        w("  {:s}  {:s}{:s}\n".format(_ref_text(g), "source={:s} ".format(g["mesh"]["source"]) if g["mesh"] else "",
                                      _mesh_text(g["mesh"]) if g["mesh"] else g.get("error", "-")))
    w("\n== Primitives ({:d}) ==\n".format(len(data["primitives"])))
    for p in data["primitives"]:
        line = "  {:s}  kind={:s}  {:s}".format(_ref_text(p), p["kind"], _kv(p["params"]) or "(no parameters)")
        line += "  encoding={!s}".format(p["encoding"])
        if p["extra_values"]:
            line += "  extra_values={:s}".format(report.format_value(p["extra_values"]))
        if p["cached_mesh"]:
            line += "  cached_mesh=({:s})".format(_mesh_text(p["cached_mesh"]))
        w(line + "\n")
    w("\n== Modifier stacks ({:d}, modifiers listed top of stack first) ==\n".format(len(data["modifier_stacks"])))
    for m in data["modifier_stacks"]:
        w("  {:s}  base={:s}  modifiers={:s}\n".format(
            _ref_text(m), _ref_text(m["base"]), ", ".join(_ref_text(r) for r in m["modifiers"]) or "-"))
    w("\n== Materials used by nodes ({:d} rows) ==\n".format(len(data["materials"])))
    for m in data["materials"]:
        pad = "  " * (m["depth"] + 1)
        if not m.get("decoded", True):
            w("{:s}[{:d}] {:s}  (not decoded)\n".format(pad, m["index"], m["class"]))
            continue
        line = "{:s}[{:d}] {:s} {:s}".format(pad, m["index"], m["class"],
                                             json.dumps(m["name"], ensure_ascii=False) if m["name"] else "(no name)")
        if m.get("repeated"):
            w(line + "  (repeated)\n")
            continue
        if m["params"]:
            line += "  " + _kv(m["params"])
        for key, mp in list(m["maps"].items()) + [("slot" + k, v) for k, v in m["unassigned_maps"].items()]:
            line += "  {:s}={:s}".format(key, "-" if mp is None else "[{:d}] {:s}{:s}".format(
                mp["index"], mp["class"], " path={:s}".format(json.dumps(mp["path"], ensure_ascii=False))
                if mp["path"] else ""))
        if m["sub_materials"] is not None:
            line += "  sub_materials={:d}  sub_ids={!s}".format(m["sub_materials"], m["sub_ids"])
        w(line + "\n")


def _print_summary(data: dict, mf, out):
    w = out.write
    c = data["container"]
    w("maxdump: {:s}\n".format(data["file"] or "<bytes>"))
    w("container: Compound File v{:d}, {:d}-byte sectors\n".format(c["version"], c["sector_size"]))

    w("\n== Streams ({:d}) ==\n".format(len(data["streams"])))
    w("  {:>12s}  {:>12s}  {:4s}  {:>6s}  {:s}\n".format("STORED", "SIZE", "GZIP", "CHUNKS", "NAME"))
    for s in data["streams"]:
        if "error" in s:
            w("  {:>12,d}  {:>12s}  {:4s}  {:>6s}  {:s}  error={:s}\n".format(
                s["stored_size"], "?", "", "", s["path"], s["error"]))
            continue
        line = "  {:>12,d}  {:>12,d}  {:4s}  {:>6d}  {:s}".format(
            s["stored_size"], s["size"], "gzip" if s["compressed"] else "-", s["top_level_chunks"], s["path"])
        if s["chunk_error"]:
            line += "  (not a clean chunk stream: {:s})".format(s["chunk_error"])
        w(line + "\n")

    cd = data["class_directory"]
    w("\n== Class directory: {:s} ({:d} classes) ==\n".format(cd["stream"] or "none", len(cd["classes"])))
    for e in cd["classes"]:
        if e["class_id"] is not None:
            cid = "class={:s} ({:s})  super={:s}".format(e["class_id"], e["class_id_u64"], e["superclass_id"])
        else:
            cid = "class=?"
        dll = "-" if e["dll_index"] is None else (
            "#{:d}".format(e["dll_index"]) if e["dll"] is not None else "0x{:08X}(none)".format(e["dll_index"]))
        line = "  #{:<4d} {:s}  dll={:s}  objects={:d}  name={:s}".format(
            e["index"], cid, dll, e["objects"], json.dumps(e["name"], ensure_ascii=False) if e["name"] else "-")
        line += "  known={:s}".format(json.dumps(e["known"]) if e["known"] else "-")
        if e["decoder"]:
            line += "  decoder={:s}".format(json.dumps(e["decoder"]))
        if e["error"]:
            line += "  error={:s}".format(e["error"])
        w(line + "\n")

    w("\n== DLL directory ({:d} entries) ==\n".format(len(data["dll_directory"])))
    for d in data["dll_directory"]:
        strings = "  ".join("{:s}={:s}".format(t, json.dumps(s, ensure_ascii=False)) for t, s in d["strings"].items())
        w("  #{:<4d} {:s}\n".format(d["index"], strings or "(no strings)"))

    w("\n== Nodes ({:d} of {:d} objects, {:d} roots) ==\n".format(len(data["nodes"]), data["objects"], data["roots"]))
    scene = mf.scene
    for n in data["nodes"]:
        node = scene.node(n["index"])
        parts = ["{:s}[{:d}] {:s}".format("  " * (n["depth"] + 1), n["index"],
                                          json.dumps(n["name"], ensure_ascii=False) if n["name"] else "(no name)")]
        if n["parent"] is None and n["parent_index"] is not None:
            parts.append("parent_index={:d}".format(n["parent_index"]))
        for key, obj in (("object", node.object), ("material", node.material), ("layer", node.layer)):
            if obj is not None:
                parts.append("{:s}={:s}".format(key, _obj_ref_text(obj)))
        if n["geometry"] is not None and (node.object is None or n["geometry"]["index"] != node.object.index):
            parts.append("geometry={:s}".format(_ref_text(n["geometry"])))
        if n["modifiers"]:
            parts.append("modifiers={:d}".format(len(n["modifiers"])))
        if node.controller is not None:
            parts.append("controller={:s}".format(_obj_ref_text(node.controller)))
            if node.transform is None:
                parts.append("transform=?")
        transform = _transform_text(node.transform, "")
        if transform:
            parts.append(transform)
        offset = _transform_text(node.object_offset, "offset_")
        if offset:
            parts.append(offset)
        w("  ".join(parts) + "\n")

    _print_decoded(data, w)

    w("\n== Classes not in the registry ({:d}) ==\n".format(len(data["unknown_classes"])))
    for u in data["unknown_classes"]:
        line = "  objects={:<6d} #{:<4d} class={:s}".format(u["objects"], u["index"], u["class_id"] or "?")
        if u["class_id_u64"]:
            line += " ({:s})  super={:s}".format(u["class_id_u64"], u["superclass_id"])
        line += "  name={:s}".format(json.dumps(u["name"], ensure_ascii=False) if u["name"] else "-")
        if u["dll"]:
            line += "  dll={:s}".format(json.dumps(u["dll"], ensure_ascii=False))
        w(line + "\n")

    w("\n== Objects asked for but without a decoder ({:d} classes) ==\n".format(len(data["undecoded"])))
    for label, count in data["undecoded"].items():
        w("  objects={:<6d} {:s}\n".format(count, label))

    w("\n== Warnings ({:d}) ==\n".format(len(data["warnings"])))
    for message in data["warnings"]:
        w("  - {:s}\n".format(message))


# -----------------------------------------------------------------------------
# Chunk trees

def chunk_rows(top_chunks, max_depth=None, preview=DEFAULT_PREVIEW, annotate=None):
    """
    Yield one JSON-compatible dict per chunk of the tree below ``top_chunks`` (see :func:`maxfile.chunks.walk`).

    ``annotate(chunk)`` may return extra keys for a top-level chunk (used for scene objects).
    """
    for depth, chunk in _chunks.walk(top_chunks, max_depth):
        row = {
            "depth": depth,
            "type": "0x{:04X}".format(chunk.type),
            "container": chunk.is_container,
            "offset": chunk.offset,
            "size": chunk.size,
        }
        if chunk.header_size != 6:
            row["header_size"] = chunk.header_size
        if depth == 0 and annotate is not None:
            row.update(annotate(chunk))
        if chunk.is_container:
            if max_depth is not None and depth >= max_depth:
                row["children"] = "not shown"
            else:
                row["children"] = len(chunk.children)
            if chunk.error:
                row["error"] = chunk.error
        else:
            payload = chunk.data
            text = _text_preview(payload)
            if text is not None:
                row["text"] = text
            else:
                row["hex"] = _hex(payload, preview)
                if 4 <= len(payload) <= 16 and len(payload) % 4 == 0:
                    row["u32"] = list(_chunks.u32s(payload))
                    row["f32"] = list(_chunks.f32s(payload))
        yield row


def _row_text(row) -> str:
    indent = "  " * (row["depth"] + 1)
    head = ""
    if "object" in row:
        head = "[{:d}] ".format(row["object"])
    line = "{:s}{:s}{:s} {:4s} size={:d} @0x{:06X}".format(
        indent, head, row["type"], "cont" if row["container"] else "leaf", row["size"], row["offset"])
    if "header_size" in row:
        line += " hdr={:d}".format(row["header_size"])
    if "class_index" in row:
        line += "  #{:d} {:s}".format(row["class_index"], row["class"])
        if row.get("node_name") is not None:
            line += " {:s}".format(json.dumps(row["node_name"], ensure_ascii=False))
    if row["container"]:
        line += "  children={!s}".format(row["children"])
    elif "text" in row:
        line += "  " + json.dumps(row["text"], ensure_ascii=False)
    else:
        line += "  " + (row["hex"] or "(empty)")
        if "u32" in row:
            line += "  u32={:s} f32={:s}".format(
                " ".join(_u32_text(v) for v in row["u32"]), " ".join(_num(v) for v in row["f32"]))
    if "error" in row:
        line += "\n{:s}  !! error: {:s}".format(indent, row["error"])
    return line


def _stream_header(stream) -> dict:
    return {
        "stream": stream.name,
        "size": stream.size,
        "stored_size": stream.stored_size,
        "compressed": stream.compressed,
        "error": stream.error,
        "warnings": stream.warnings,
    }


def _dump_chunks(mf, args, out) -> int:
    if args.stream is not None:
        stream = mf.stream(args.stream)
        top = stream.chunks
        annotate = None
    else:
        stream = mf.stream(SCENE_STREAM)
        scene = mf.scene
        objects = scene.objects
        if args.object is not None:
            if not 0 <= args.object < len(objects):
                raise maxfile.MaxFileError("object {:d} out of range (the scene has {:d} objects)".format(
                    args.object, len(objects)))
            objects = [objects[args.object]]
        by_chunk = {id(obj.chunk): obj for obj in scene.objects}
        top = [obj.chunk for obj in objects]

        def annotate(chunk):
            obj = by_chunk[id(chunk)]
            node = scene.node(obj.index)
            return {"object": obj.index, "class_index": obj.class_index, "class": obj.class_label(),
                    "node_name": node.name if node is not None else None}

    rows = chunk_rows(top, args.depth, args.preview, annotate)
    header = _stream_header(stream)
    if args.json:
        header["chunks"] = list(rows)
        _write_json(header, out)
        return 0
    flags = []
    if stream.compressed:
        flags.append("gzip, {:,d} bytes stored".format(stream.stored_size))
    out.write("== Stream {:s}: {:,d} bytes{:s}, {:d} top-level chunk(s) ==\n".format(
        stream.name, stream.size, " (" + "; ".join(flags) + ")" if flags else "", len(stream.chunks)))
    for row in rows:
        out.write(_row_text(row) + "\n")
    if stream.error:
        out.write("!! top level: {:s}\n".format(stream.error))
    for message in stream.warnings:
        out.write("!! {:s}\n".format(message))
    return 0


# -----------------------------------------------------------------------------
# Decoded view of one object

def _param_entry_text(entry) -> str:
    g = entry.guessed
    parts = ["id=0x{:04X}".format(entry.param_id), "chunk=0x{:04X}".format(entry.chunk_type),
             "bytes={:d}".format(len(entry.raw))]
    for key in ("float", "int", "color", "rgba_color"):
        if key in g:
            parts.append("{:s}={:s}".format(key, report.format_value(g[key])))
    return "  ".join(parts)


def decoded_object(mf, index: int) -> dict:
    """What the decoders and the generic readers make of scene object ``index`` (JSON-compatible)."""
    from .objects.maps import is_map_like, read_map
    scene = mf.scene
    if not 0 <= index < len(scene.objects):
        raise maxfile.MaxFileError("object {:d} out of range (the scene has {:d} objects)".format(
            index, len(scene.objects)))
    obj = scene.objects[index]
    info = registry.find_decoder(obj.class_id, obj.superclass_id)
    before = len(scene.warnings)
    value = scene.decode(obj) if info is not None else None
    result = {
        "object": index,
        "class": obj.class_label(),
        "class_index": obj.class_index,
        "class_id": str(obj.class_id) if obj.class_id is not None else None,
        "decoder": info.name if info is not None else None,
        "kind": info.kind if info is not None else None,
        "value": report.to_plain(value),
        "references": {str(slot): _obj_ref(scene.objects[i]) for slot, i in sorted(obj.references.items())},
    }
    node = scene.node(index)
    if node is not None:
        base, modifiers = scene.resolve_geometry(node)
        result["node"] = {
            "name": node.name, "parent_index": node.parent_index,
            "transform": _transform_json(node.transform), "object_offset": _transform_json(node.object_offset),
            "geometry": _obj_ref(base), "modifiers": [_obj_ref(m) for m in modifiers],
        }
    # Generic, structural readings: useful for classes without a decoder.
    result["param_block"] = report.to_plain(scene.param_block(obj))
    ctx = scene.context
    result["map"] = report.to_plain(read_map(obj, ctx)) if is_map_like(obj, ctx) else None
    result["warnings"] = scene.warnings[before:]
    return result


def _print_decoded_object(data: dict, mf, out):
    w = out.write
    w("== Object [{:d}] {:s}  #{:d}  class={!s}  decoder={:s} ==\n".format(
        data["object"], data["class"], data["class_index"], data["class_id"],
        json.dumps(data["decoder"]) + " kind=" + data["kind"] if data["decoder"] else "none"))
    refs = data["references"]
    w("references: {:s}\n".format("  ".join("{:s}={:s}".format(k, _ref_text(v)) for k, v in refs.items()) or "-"))
    if "node" in data:
        n = data["node"]
        w("node: name={:s}  parent_index={!s}  geometry={:s}  modifiers={:s}\n".format(
            json.dumps(n["name"], ensure_ascii=False), n["parent_index"], _ref_text(n["geometry"]),
            ", ".join(_ref_text(m) for m in n["modifiers"]) or "-"))
    scene = mf.scene
    obj = scene.objects[data["object"]]
    if data["decoder"]:
        w("\ndecoded:\n")
        value = scene.decode(obj)
        w(report.format_value(value) + "\n" if value is not None else "  None (see warnings)\n")
    block = scene.param_block(obj)
    w("\nas a parameter block ({:d} leaf entries; values are guesses from the payload end):\n".format(
        len(block.entries)))
    for entry in block.entries[:64]:
        w("  " + _param_entry_text(entry) + "\n")
    if len(block.entries) > 64:
        w("  ... ({:d} total)\n".format(len(block.entries)))
    if data["map"] is not None:
        m = data["map"]
        w("\nas a map: path={:s}  path_source={!s}  asset_index={!s}\n".format(
            json.dumps(m["path"], ensure_ascii=False), m["path_source"], m["asset_index"]))
    if data["warnings"]:
        w("\nwarnings:\n")
        for message in data["warnings"]:
            w("  - {:s}\n".format(message))


# -----------------------------------------------------------------------------
# Entry point

def _parser():
    parser = argparse.ArgumentParser(
        prog="maxdump",
        description="Show the structure of a .max file as maxfile reads it.",
    )
    parser.add_argument("file", help="the .max file")
    parser.add_argument("--chunks", action="store_true", help="print the chunk tree of the scene objects")
    parser.add_argument("--object", type=int, metavar="N", help="with --chunks: only scene object N")
    parser.add_argument("--depth", type=int, metavar="D",
                        help="with --chunks/--stream: only chunks down to depth D (0 = objects / top level)")
    parser.add_argument("--stream", metavar="NAME", help="print the chunk tree of any stream (e.g. ClassDirectory3)")
    parser.add_argument("--preview", type=int, default=DEFAULT_PREVIEW, metavar="BYTES",
                        help="bytes of hex shown per leaf chunk (default {:d})".format(DEFAULT_PREVIEW))
    parser.add_argument("--decode", action="store_true",
                        help="with --object: print what the decoders make of the object instead of its chunks")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv=None, out=None) -> int:
    """Run maxdump; returns the exit status (0 = success, 1 = unreadable file, 2 = bad arguments)."""
    out = out or sys.stdout
    parser = _parser()
    args = parser.parse_args(argv)
    if args.decode and args.object is None:
        parser.error("--decode needs --object N")
    if args.object is not None and not args.decode:
        args.chunks = True
    if args.stream is not None and args.object is not None:
        parser.error("--object only applies to the Scene stream; don't combine it with --stream")
    if args.depth is not None and args.depth < 0:
        parser.error("--depth must be 0 or more")
    try:
        with maxfile.open(args.file) as mf:
            if args.decode:
                data = decoded_object(mf, args.object)
                if args.json:
                    _write_json(data, out)
                else:
                    _print_decoded_object(data, mf, out)
                return 0
            if args.chunks or args.stream is not None:
                return _dump_chunks(mf, args, out)
            data = summary(mf)
            if args.json:
                _write_json(data, out)
            else:
                _print_summary(data, mf, out)
            return 0
    except BrokenPipeError:
        # Output piped into `head` or similar: stop quietly, and keep Python from complaining at exit.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    except (maxfile.MaxFileError, OSError) as ex:
        sys.stderr.write("maxdump: error: {:s}: {:s}\n".format(args.file, str(ex)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
