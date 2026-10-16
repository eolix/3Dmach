# SPDX-FileCopyrightText: 2026 PROJECT_NAME Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Import report: what an import brought in, what it skipped and why (ROADMAP Phase 2g).

The report collects counts while the importer runs, renders as plain text that users can attach to bug reports,
and is stored in a Blender text block by :func:`store_in_text` (the only part that needs ``bpy``).
"""

__all__ = (
    "ImportReport",
    "store_in_text",
)

import collections
import dataclasses


@dataclasses.dataclass
class ImportReport:
    source: str = ""
    imported: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    # (category, class name) -> count, e.g. ("modifier", "Edit Poly").
    unsupported: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    missing_textures: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    errors: list = dataclasses.field(default_factory=list)

    def add_imported(self, category, count=1):
        """Count imported items: ``category`` is e.g. "objects", "materials", "modifiers"."""
        self.imported[category] += count

    def add_unsupported(self, category, name, count=1):
        """Record something that was skipped or replaced by a placeholder."""
        self.unsupported[(category, name)] += count

    def add_missing_texture(self, path):
        if path not in self.missing_textures:
            self.missing_textures.append(path)

    def warn(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)

    @property
    def is_clean(self):
        return not (self.unsupported or self.missing_textures or self.warnings or self.errors)

    def summary(self):
        """One line for the status bar."""
        parts = ["{:d} {:s}".format(count, category) for category, count in sorted(self.imported.items())]
        text = "Imported " + (", ".join(parts) if parts else "nothing")
        issues = sum(self.unsupported.values()) + len(self.missing_textures) + len(self.warnings) + len(self.errors)
        if issues:
            text += "; {:d} issue(s), see the import report".format(issues)
        return text

    def to_text(self):
        lines = ["Import report", "=" * 13]
        if self.source:
            lines.append("File: " + self.source)
        lines.append("")
        lines.append("Imported:")
        if self.imported:
            lines.extend("  {:s}: {:d}".format(category, count) for category, count in sorted(self.imported.items()))
        else:
            lines.append("  nothing")
        if self.unsupported:
            lines.append("")
            lines.append("Not supported yet (skipped or placeholder):")
            for (category, name), count in sorted(self.unsupported.items()):
                lines.append("  {:s}: {:s} x{:d}".format(category, name, count))
        if self.missing_textures:
            lines.append("")
            lines.append("Missing textures:")
            lines.extend("  " + path for path in self.missing_textures)
        for title, items in (("Warnings:", self.warnings), ("Errors:", self.errors)):
            if items:
                lines.append("")
                lines.append(title)
                lines.extend("  " + item for item in items)
        return "\n".join(lines) + "\n"


def store_in_text(report, name="Import Report"):
    """Write the report into a text block (replacing its contents) and return it."""
    import bpy
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text.clear()
    text.write(report.to_text())
    return text
