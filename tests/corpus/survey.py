#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Run ``maxfile`` over every file in the local corpus and summarise what it can and can't read.

Usage::

    python3 tests/corpus/survey.py [--jobs N] [--limit N] [--json OUT.json] [CORPUS_DIR]

For each file: whether it opens (or the error), its streams, Max release and units, class and node counts,
classes the registry doesn't know, what each node's object decodes to (through modifier stacks: the base object,
plus the stack's modifiers and what they decode to) and what node materials decode to. The summary aggregates
those across the corpus; ``--json`` keeps the per-file records for later investigation with ``maxdump``.
"""

import argparse
import collections
import concurrent.futures
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pylibs", "maxfile"))

import corpus  # noqa: E402


def survey_file(path):
    import maxfile
    record = {"path": path, "size": os.path.getsize(path)}
    start = time.monotonic()
    if record["size"] == 0:
        record["status"] = "empty"
        return record
    try:
        with maxfile.open(path) as mf:
            record["streams"] = sorted(e.path_str for e in mf.streams if e.kind == "stream")
            scene = mf.scene
            record["objects"] = len(scene.objects)
            record["nodes"] = len(scene.nodes)
            record["classes"] = len(mf.class_directory.entries) if hasattr(mf.class_directory, "entries") else None
            record["unknown_classes"] = [(u.entry.label(), u.count) for u in mf.unknown_classes()]
            record["max_release"] = getattr(mf, "max_release", None)
            units = getattr(mf, "units", None)
            record["units"] = units.unit if units is not None else None
            kinds = collections.Counter()
            modifiers = collections.Counter()
            materials = collections.Counter()
            decode_errors = collections.Counter()

            def label(obj, decoded):
                return type(decoded).__name__ if decoded is not None else "undecoded:" + obj.class_label()

            for node in scene.nodes:
                obj = node.object
                if obj is None:
                    kinds["(none)"] += 1
                    continue
                try:
                    if hasattr(scene, "resolve_geometry"):
                        base, mods = scene.resolve_geometry(node)
                        for mod in mods:
                            modifiers[mod.class_label() + " -> " + label(mod, scene.decode(mod))] += 1
                        if base is None:
                            kinds["(stack without base)"] += 1
                            continue
                        obj = base
                    kinds[label(obj, scene.decode(obj))] += 1
                    if node.material is not None:
                        materials[label(node.material, scene.decode(node.material))] += 1
                except Exception as ex:  # Should never happen: decoders report problems as warnings.
                    decode_errors[type(ex).__name__] += 1
                    continue
            record["node_objects"] = dict(kinds)
            record["modifiers"] = dict(modifiers)
            record["node_materials"] = dict(materials)
            record["decode_exceptions"] = dict(decode_errors)
            record["warnings"] = len(mf.warnings)
            record["warning_samples"] = list(mf.warnings[:5])
            record["status"] = "ok"
    except maxfile.MaxFileError as ex:
        record["status"] = "error"
        record["error"] = "{:s}: {:s}".format(type(ex).__name__, str(ex))
    except Exception as ex:  # A crash in maxfile itself: always a bug.
        record["status"] = "crash"
        record["error"] = "{:s}: {:s}".format(type(ex).__name__, str(ex))
        record["traceback"] = traceback.format_exc()[-2000:]
    record["seconds"] = round(time.monotonic() - start, 3)
    return record


def summarise(records):
    status = collections.Counter(r["status"] for r in records)
    lines = ["{:d} files: ".format(len(records)) + ", ".join("{:s} {:d}".format(k, v) for k, v in status.most_common())]
    errors = collections.Counter(r["error"].split(":")[0] + ": " + r["error"].split(":", 1)[1][:80]
                                 for r in records if r["status"] in {"error", "crash"})
    if errors:
        lines.append("\nErrors and crashes (by message):")
        lines.extend("  {:5d}  {:s}".format(n, msg) for msg, n in errors.most_common(25))
    ok = [r for r in records if r["status"] == "ok"]
    streams = collections.Counter(s for r in ok for s in r["streams"])
    lines.append("\nStreams (files containing them):")
    lines.extend("  {:5d}  {:s}".format(n, s) for s, n in streams.most_common(30))
    for key, title in (("max_release", "Max release x 1000"), ("units", "System units")):
        values = collections.Counter(str(r.get(key)) for r in ok)
        lines.append("\n{:s}: ".format(title) + ", ".join("{:s} {:d}".format(k, n) for k, n in values.most_common()))
    for key, title in (("node_objects", "What node objects decode to, through modifier stacks (all files)"),
                       ("modifiers", "Modifiers on node stacks -> decoded as"),
                       ("node_materials", "Node materials decode to")):
        kinds = collections.Counter()
        for r in ok:
            kinds.update(r.get(key, {}))
        lines.append("\n{:s}: {:d} total".format(title, sum(kinds.values())))
        lines.extend("  {:7d}  {:s}".format(n, k) for k, n in kinds.most_common(40))
    lines.append("\nWarnings: {:d} in {:d} files".format(sum(r["warnings"] for r in ok),
                                                         sum(1 for r in ok if r["warnings"])))
    unknown = collections.Counter()
    unknown_files = collections.Counter()
    for r in ok:
        for name, count in r["unknown_classes"]:
            unknown[name] += count
            unknown_files[name] += 1
    lines.append("\nClasses not in the registry (objects, files):")
    lines.extend("  {:7d} {:5d}  {:s}".format(unknown[k], unknown_files[k], k) for k, _ in unknown.most_common(40))
    exceptions = collections.Counter()
    for r in ok:
        exceptions.update(r["decode_exceptions"])
    if exceptions:
        lines.append("\nDecoder exceptions (should be none): " + ", ".join(
            "{:s} x{:d}".format(k, v) for k, v in exceptions.most_common()))
    slowest = sorted(ok, key=lambda r: r["seconds"], reverse=True)[:5]
    lines.append("\nSlowest: " + "; ".join("{:.1f}s {:.0f}MB {:s}".format(
        r["seconds"], r["size"] / 2**20, os.path.basename(r["path"])) for r in slowest))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("corpus_dir", nargs="?", default=None)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--limit", type=int, default=0, help="Only the first N files (sorted by path)")
    parser.add_argument("--json", default=None, help="Write per-file records to this JSON file")
    args = parser.parse_args(argv)

    cases, problems = corpus.load_corpus(args.corpus_dir)
    for problem in problems:
        print("manifest:", problem)
    paths = sorted(case.path for case in cases)
    if args.limit:
        paths = paths[:args.limit]
    records = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for record in pool.map(survey_file, paths, chunksize=4):
            records.append(record)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(records, fh, indent=1)
    print(summarise(records))
    return 1 if any(r["status"] == "crash" for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
