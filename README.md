# interface-test-kit

Interface test software that runs **on** a Linux embedded or panel PC and
checks its serial ports (including the handshake lines), USB ports, Ethernet
and CAN. The interfaces are fitted with test equipment: loopback plugs,
labelled USB test sticks, a network cable and a CAN cable. An operator is
guided through the test step by step and only has to answer Y/N.

It is written for the two situations where this test matters:

- **End-of-line test:** every unit gets a test report before it is shipped.
- **RMA:** reproduce the fault the customer reported, and prove the repair
  afterwards (both runs are stored under the RMA number).

Faulty test equipment is the classic time sink in both cases: a worn
loopback plug makes a good unit fail. That is why there is an **equipment
self-test** (`itk selftest`), which checks the plugs, sticks and cables on a
known-good reference unit.

Everything can be tried without hardware: `itk demo` runs a full session
against a simulated unit, with faults you can switch on.

## Quick start

Needs Linux and Python 3.10+.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

itk demo                      # healthy unit -> PASS
itk demo --fault serial_cts   # broken handshake line -> FAIL in "Serial 1"
itk demo --list-faults
```

```
Scan or enter the serial number: EPC-24-00137
Profile: EPC-24 variant B (demo) (v1). Correct? [Y/N] Y
Plug the loopback plugs into COM1 and COM2, the two test sticks into the blue USB ports, ...
Press Enter when ready.
Serial 1: handshake line faulty (RTS->CTS). Check the loopback plug; if it is fine, send the unit to repair.
Retry this step? [Y/N] N
  [FAIL] Serial 1         Serial 1: handshake line faulty (RTS->CTS). Check the loopback plug; ...
  [PASS] Serial 2
  [PASS] USB
  [PASS] LAN1
  [PASS] CAN
Is the power LED green? [Y/N] Y
  [PASS] Power LED

========================================
   RESULT: FAIL
========================================
Same failure on several units? Run the equipment self-test.
Report saved: reports/EPC-24-00137_20261028-134954
```

## Injectable faults (demo)

| `--fault` | Defect | Caught by |
|---|---|---|
| `serial_cts` | RTS→CTS line broken | Serial 1 |
| `serial_data` | no data comes back | Serial 1 |
| `usb_missing` | only one test stick plugged in | USB |
| `usb_slow` | test sticks far too slow | USB |
| `usb_wrong_speed` | USB 3 port only runs at 480 Mbit/s | USB |
| `usb_no_label` | a stick without the `ITKTEST` label | USB |
| `eth_no_link` | no Ethernet link | LAN1 |
| `eth_speed` | link at 100 instead of 1000 Mbit/s | LAN1 |
| `can_no_ack` | frames sent from can0 never arrive | CAN |
| `led_off` | the operator sees the power LED off | Power LED |

## What is tested

| Step type | What it checks |
|---|---|
| `serial` | Test pattern (all 256 byte values plus random data) at every baud rate in the profile, then each handshake line of the loopback plug in both states, with the other outputs held opposite so shorts show up. Reports the exact line, e.g. `DTR->DSR`. |
| `usb` | Number of mounted test sticks, optionally which port each one is in, the negotiated USB speed (catches a USB 3 port running at USB 2), and a write/read/compare of a test file with throughput limits. |
| `ethernet` | Link, negotiated speed and duplex, ping to a counterpart with a packet-loss limit. |
| `can` | Two CAN ports wired together exchange standard and extended frames in both directions; on real CAN hardware the bitrate is set first and the controller must end in `ERROR-ACTIVE`. |
| `confirm` | A manual check: the operator looks at something and answers Y/N. |

**Retries:** loose plugs happen. When a step fails, the operator can retry it.
A step counts as PASS when its first attempt passes, or when its last **two**
attempts pass in a row. After a fail followed by a pass, the tool runs the
step once more on its own. The limit is `max_attempts` (default 4). The
report lists every attempt and marks the step "passed after retry".

### USB safety rules

The USB test never formats anything and never writes to a block device. It
only writes one file, `itk-test.bin`, into the mount point of a **mounted**
filesystem on a **USB** disk whose **label starts with** the profile's label
(default `ITKTEST`, so `ITKTEST1`, `ITKTEST2` work for several sticks). The
file is deleted afterwards. A stick with another label is ignored and
listed in the report.

## Running it on a test station

```bash
itk run                          # end-of-line test
itk run --rma RMA-2026-0042      # RMA: the number goes into the report and folder name
itk run --only serial-1,usb      # RMA: just these steps
itk selftest                     # check the test equipment on the reference unit
itk sync                         # upload reports saved while the network drive was down
itk check-profile profiles/*.yaml
```

The flow for the operator:

1. Scan or type the serial number. If it does not match the profile's pattern, the tool asks again.
2. The profile is chosen automatically (single profile, or DMI / device-tree match). Otherwise the operator picks it from a numbered list. Then the operator confirms it.
3. Before anything runs, the tool checks that every port and interface exists and is accessible.
4. The setup instruction is shown: what to plug in where.
5. The steps run, one line each. Manual checks and retries ask Y/N.
6. A large `RESULT: PASS` / `FAIL` / `ABORTED` banner appears, then the report is written.

Ctrl+C aborts cleanly: the steps finished so far are written with the result `ABORTED`.

Exit codes: `0` PASS, `1` FAIL, `2` aborted or configuration error.

### Station file

`/etc/itk/station.yaml` (or `--station`, or `$ITK_STATION`). See
[`examples/station.yaml`](examples/station.yaml):

```yaml
report_dir: /mnt/test-reports/itk   # network drive, mounted by the OS
require_mount: true                 # an unmounted share counts as unreachable
spool_dir: /var/lib/itk/spool       # reports wait here until `itk sync`
profile_dir: /etc/itk/profiles
name: EOL-STATION-1
ask_operator: false
```

If the network drive is not reachable, the report is saved in `spool_dir`
and the operator is told so. The next run, or `itk sync`, uploads it. With
`require_mount: true`, a share that is not mounted is noticed instead of
quietly filling the empty mount-point folder on the local disk.

### Profiles

One YAML file per product variant. The product owner decides what is
tested, and the profile writes it down. A complete, commented example is in
[`examples/profiles/epc24-variant-b.yaml`](examples/profiles/epc24-variant-b.yaml):

```yaml
name: EPC-24 variant B
version: 3                      # stored in every report
detect: {dmi_product_name: EPC-24B}
serial_number: {pattern: "^EPC-24-\\d{5}$"}
setup: Plug the loopback plugs into COM1 and COM2, ...
steps:
  - {type: serial, name: Serial 1, port: /dev/ttyS0, loopback: 9pin-full, bauds: [9600, 115200]}
  - {type: usb, name: USB, count: 2, ports: [1-1, 2-1], min_write_mbs: 10, min_speed_mbps: 5000}
  - {type: ethernet, name: LAN1, iface: eth0, speed: 1000, duplex: full, ping: 192.168.100.1}
  - {type: can, name: CAN, pair: [can0, can1], bitrate: 500000}
  - {type: confirm, name: Power LED, prompt: "Is the power LED green?"}
```

Step ids for `--only` come from the name (`Serial 1` → `serial-1`) unless a
step sets `id:`. `itk check-profile` reports mistakes with their line
number, including misspelled fields.

**Reference profiles** (`reference: true`) are only offered by `itk selftest`.
A step can ask for the equipment's number (`equipment: Loopback plug number`),
which is stored in the self-test report. In self-test mode the messages talk
about the equipment instead of the unit, for example "Loopback plug on Serial 1
faulty (DTR->DSR not connected)". See
[`examples/profiles/reference-epc24.yaml`](examples/profiles/reference-epc24.yaml).

### Reports

Each run gets its own folder: `<serial>[_<rma>]_<YYYYmmdd-HHMMSS>/`
(self-tests go to `selftest/`). It contains:

- `result.json`: serial number, RMA, profile name and version, station,
  operator, start and end time, tool version, result, and per step every
  attempt with its message, details and measurements (value, unit, limits,
  passed). This is the interface for further tools.
- `report.txt`: the same as plain, printable text.

## Hardware validation status

This first version is developed and tested **in simulation only**. The
simulation covers the logic, but the following still has to be verified on
real hardware:

- Modem control lines through real UARTs and real loopback plugs. The data
  path is tested through a Linux pseudo-terminal with pyserial; the lines are
  tested against a simulated plug.
- USB throughput and negotiated speed on real sticks and ports. The sysfs
  layout and `lsblk` output are faked in the tests.
- CAN on real controllers and transceivers, including setting the bitrate
  and reading the error state. The SocketCAN code itself is tested against
  a virtual `vcan` interface.
- `ip` and `ping` behaviour on the target distributions.

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

The CAN round-trip test needs a `vcan0` interface and is skipped otherwise.
Without root you can run it in a user network namespace:

```bash
unshare -rn sh -c 'ip link add vcan0 type vcan && ip link set up vcan0 && pytest tests/test_can.py'
```

## Roadmap

- RS485 (half-duplex loopback with RTS direction control)
- GPIO loopback pairs, audio loopback
- Guided checks for display, keyboard and touch
- Tracking of test equipment across runs
- CAN partner mode, Ethernet throughput (iperf3), RMA before/after comparison

## License

MIT
