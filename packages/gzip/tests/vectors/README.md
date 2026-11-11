# Known compressed data

`payload.bin` contains a text header, all 256 byte values repeated four times,
and a binary trailer. `known.gz` is the checked-in encoded form. The installed
decoder must recover the exact bytes before the command roundtrip tests run.

Generated with CPython 3.15.2 using `gzip.compress(payload, mtime=0)`,
`bz2.compress(payload)` or `lzma.compress(payload)` for those formats.
The Zstandard vector used `*** Zstandard CLI (64-bit) v1.5.7, by Yann Collet ***` with `zstd -q --check -c`.
The fixture is original test data and contains no third-party material.
