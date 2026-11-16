# Changelog

## 0.1.1 – 2026-11-16

- `itk demo`: the USB step now reports throughput a real test stick could reach (42/138 MB/s
  write/read on USB 3, 17.5/34 MB/s on USB 2). It used to time the local disk behind the
  simulated sticks and showed up to 4000 MB/s on a 5 Gbit/s port. Real runs were not affected.

## 0.1.0 – 2026-10-28

First version.

- `itk run`: operator-guided interface test of a unit against a per-variant YAML profile,
  with `--rma` and `--only` for repair work.
- Step types: `serial` (data at several baud rates plus handshake lines through a loopback
  plug), `usb` (labelled test sticks: count, port, negotiated speed, write/read/compare,
  throughput), `ethernet` (link, speed, duplex, ping), `can` (two ports wired together,
  SocketCAN), `confirm` (manual Y/N check).
- Retry rule: a step passes on its first attempt or when its last two attempts pass.
- `itk selftest`: equipment self-test on a reference unit, with equipment numbers in the report.
- Reports as `result.json` and `report.txt`; spooled locally when the network drive is
  unreachable, uploaded by the next run or `itk sync`.
- `itk check-profile` with line numbers; `itk demo` with ten injectable faults.
