# Modifier stacks

How the importer converts Max modifier stacks (`scripts/addons_core/mx_io_max/modifiers/convert.py`). Each
supported modifier becomes a Blender modifier with the same name, in the same order, so the stack stays
editable. The stack is imported up to the first unsupported modifier, which is listed in the import report.
"Collapse stack on import" applies everything instead.

| Max modifier | Blender | Differences |
|---|---|---|
| TurboSmooth, MeshSmooth, OpenSubdiv | Subdivision Surface (iterations, render iterations) | |
| Shell | Solidify (inner + outer amount → thickness and offset, even thickness) | No segments |
| Symmetry | Mirror with bisect and flip, merge threshold | Mirrored about the object origin, not the gizmo |
| Mirror | Mirror without merge | |
| Chamfer | Bevel on edges above 30° | Max Chamfer has many more options |
| Bend / Twist / Taper | Simple Deform (angle/amount, axis) | Bend direction and limits not applied |
| Noise | Displace with a Clouds texture | One strength along the normals instead of per-axis |
| Push | Displace along normals | |
| Relax | Smooth | |
| Optimize, ProOptimizer | Decimate | |
| Lattice | Wireframe | |
| Normal (flip) | Geometry Nodes "Flip Normals" | |
| Turn to Poly | nothing needed | |
| Edit Poly, Edit Mesh, UVW Map, Unwrap UVW, FFD, Skin, … | not yet | Reported; the stack stops there |

Parameters come from `maxfile`'s decoders. Until a modifier's parameter block is decoded, the modifier is
added with Max's default values.
