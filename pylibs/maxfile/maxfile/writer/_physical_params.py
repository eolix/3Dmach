# SPDX-FileCopyrightText: 2026 3Dmach Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The parameter block of a Physical Material: the dominant record of each parameter in the 106 sampled Physical
Materials of the 2018 corpus files ("n/106" = blocks with this exact value), in their record order (the same in
all 106). The class doesn't exist in Max 2015; see ``maxfile/writer/physical.py``.

Tuples are ``maxfile.writer.pblock.R`` arguments: id, type, flags_a, flags_b, extra, value flags, value (or
``None, (), raw bytes``: the maps 100-133 have no value, their objects sit in reference slots 0-24 in record
order; the maps 250-270 are inline indices, all empty).
"""

# Corpus: 8 rollout entries (100/106) and the Max version word of the 0x0009 header (1 in all 106).
ROLLOUTS = (1, 0, 1, 1, 1, 0, 1, 1)
VERSION_WORD = 1
# Dominant record order: 106/106 blocks.
DESC_VERSION = 10  # 20/106
RECORDS = (
    (0x00, 1, 0x0000, 0x82, 1, 0x40, 1),                                                              # 55/106
    (0x01, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 91/106
    (0x02, 23, 0x0001, 0x82, 1, 0xc0, (0.5, 0.5, 0.5, 1.0)),                                          # 17/106
    (0x03, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 56/106
    (0x04, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 19/106
    (0x05, 4, 0x0000, 0x82, 1, 0x40, 1),                                                              # 60/106
    (0x06, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 104/106
    (0x0a, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 1.0, 1.0, 1.0)),                                          # 65/106
    (0x0b, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 85/106
    (0x0c, 4, 0x0000, 0x82, 1, 0x40, 1),                                                              # 78/106
    (0x0d, 0, 0x0001, 0x92, 1, 0xc0, 0.05),                                                           # 63/106
    (0x0e, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 102/106
    (0x0f, 0, 0x0001, 0x92, 1, 0xc0, 5.0),                                                            # 103/106
    (0x14, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 101/106
    (0x15, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 102/106
    (0x16, 1, 0x0000, 0x92, 1, 0x40, 0),                                                              # 104/106
    (0x17, 1, 0x0000, 0x82, 1, 0x40, 0),                                                              # 104/106
    (0x1e, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 105/106
    (0x1f, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 1.0, 1.0, 1.0)),                                          # 68/106
    (0x20, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 106/106
    (0x23, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 52/106
    (0x24, 4, 0x0000, 0x82, 1, 0x40, 0),                                                              # 68/106
    (0x22, 4, 0x0000, 0x82, 1, 0x40, 1),                                                              # 62/106
    (0x21, 0, 0x0001, 0x92, 1, 0xc0, 1.4),                                                            # 43/106
    (0x25, 4, 0x0000, 0x82, 1, 0x40, 0),                                                              # 106/106
    (0x28, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 106/106
    (0x29, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 1.0, 1.0, 1.0)),                                          # 106/106
    (0x2a, 0, 0x0001, 0x92, 1, 0xc0, 10.0),                                                           # 106/106
    (0x2b, 0, 0x0001, 0x92, 1, 0xc0, 1.0),                                                            # 106/106
    (0x2c, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 0.5, 0.25, 1.0)),                                         # 106/106
    (0x32, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 104/106
    (0x33, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 1.0, 1.0, 1.0)),                                          # 106/106
    (0x34, 0, 0x0001, 0x92, 1, 0xc0, 1500.0),                                                         # 104/106
    (0x36, 0, 0x0001, 0x92, 1, 0xc0, 6500.0),                                                         # 105/106
    (0x3c, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 92/106
    (0x3d, 23, 0x0001, 0x82, 1, 0xc0, (1.0, 1.0, 1.0, 1.0)),                                          # 94/106
    (0x3e, 0, 0x0001, 0x92, 1, 0xc0, 0.0),                                                            # 85/106
    (0x3f, 4, 0x0000, 0x82, 1, 0x40, 0),                                                              # 106/106
    (0x40, 0, 0x0001, 0x92, 1, 0xc0, 0.5),                                                            # 91/106
    (0x41, 0, 0x0001, 0x92, 1, 0xc0, 0.5),                                                            # 91/106
    (0x42, 0, 0x0001, 0x92, 1, 0xc0, 1.52),                                                           # 76/106
    (0x64, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x65, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x66, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x67, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x68, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x69, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6a, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6b, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6c, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6d, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6e, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x6f, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x70, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x71, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x72, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x73, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x74, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x75, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x76, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x77, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x78, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x82, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x83, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x84, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x85, 15, 0x0000, 0x1081, 0, 0x40, None, (), bytes.fromhex('')),                                 # 106/106
    (0x96, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0x97, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 82/106
    (0x98, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 75/106
    (0x99, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 74/106
    (0x9a, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 73/106
    (0x9b, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0x9c, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0x9d, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0x9e, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0x9f, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa0, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 72/106
    (0xa1, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa2, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa3, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa4, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa5, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa6, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa7, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 73/106
    (0xa8, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xa9, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xaa, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xb4, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 74/106
    (0xb5, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 106/106
    (0xb6, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 74/106
    (0xb7, 4, 0x0000, 0x82, 0, 0x40, 1),                                                              # 104/106
    (0xe6, 0, 0x0001, 0x92, 0, 0xc0, 0.3),                                                            # 97/106
    (0xe7, 0, 0x0001, 0x92, 0, 0xc0, 0.3),                                                            # 89/106
    (0xe8, 0, 0x0001, 0x92, 0, 0xc0, 1.0),                                                            # 72/106
    (0xfa, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0xfb, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0xfc, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0xfe, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0xff, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0xfd, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                         # 106/106
    (0x100, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x101, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x102, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x103, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x104, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x105, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x106, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x107, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x108, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x109, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x10a, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x10b, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x10c, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x10d, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
    (0x10e, 15, 0x2900, 0x1081, 0, 0x40, None, (), bytes.fromhex('ffffffff')),                        # 106/106
)
