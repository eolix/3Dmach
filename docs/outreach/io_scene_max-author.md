# Draft: message to the io_scene_max author

For the maintainer to send (ROADMAP Phase 2a). Sebastian Sille maintains `io_scene_max`; the contact in its
extension manifest is `NRG Sille <nrgsille@gmx.de>`, and the add-on's website is
https://github.com/nrgsille76/io_scene_max.

---

**Subject:** io_scene_max: collaboration on .max format knowledge

Hi Sebastian,

I'm starting PROJECT_NAME, an open-source (GPL) fork of Blender aimed at people coming from Max-style
workflows. Opening `.max` files is a core part of it. Your io_scene_max importer has been the best public
reference on the format, so thank you for it.

We're writing a separate pure-Python `.max` parser with no Blender dependency, so it can be unit-tested and
reused. We'll use io_scene_max as a reference and credit you, Jens M. Plonka and Philippe Lagadec in our format
notes. Everything we learn is documented openly (format notes, a `maxdump` inspection tool, and a test corpus of
redistributable `.max` files with reference exports), and we'd be glad if it helps io_scene_max too.

Two questions:

1. Would you be interested in collaborating: sharing findings, test files, or fixes in both directions?
2. A licence detail: the source headers in io_scene_max 1.9.2 say GPL-2.0-or-later, while the extension
   manifest says GPL-3.0-or-later. Which one do you intend? It matters only if we ever adapt code directly, and
   either works for us.

Thanks,
[name]
