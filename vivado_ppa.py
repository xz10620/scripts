#!/usr/bin/env python3
"""vivado_ppa.py — Vivado utilization + timing -> ASIC gate count, area and clock estimate.

Parses a Vivado `report_utilization` file (post-synth or post-route), prints the
resource utilization, converts the primitive counts to NAND2-equivalent gates
(GE) and projects silicon area for several process nodes. If a matching
report_timing_summary file is found (post_X_util.rpt -> post_X_timing.rpt), it
also estimates the ASIC clock frequency of the worst FPGA path at each node.

Usage:
    python3 syn/vivado_ppa.py [report.rpt] [--nodes 3 5 6 9 16] [--util 0.7]
                               [--timing post_route_timing.rpt]

The default report is syn/vivado/post_synth_util.rpt next to this script.
Use the post-route timing report for frequency: post-synth path delays use
estimated routing.

This is an early architecture estimate, not a synthesis result. GE factors are
typical mapped-logic averages; area uses a practical NAND2 (X1, HD library)
cell area per node and SRAM bitcell size with a macro efficiency factor. Expect +/-30-50% error versus real ASIC synthesis.

Frequency is given as a slow-corner (SS) signoff range from two methods:
  low  - FPGA path delay / ASIC speedup at the FPGA's own node (Kuon & Rose,
         ~3.4x), scaled to each node by FO4 delay ratio.
  high - path logic levels converted to FO4 gate delays (+ flop overhead),
         times the node's typical FO4, derated to the SS corner.
Expect +/-30%; the result assumes the RTL pipelining is unchanged.
"""

import argparse
import math
import os
import re
import sys

# ── NAND2-equivalent gates per Vivado primitive ──────────────────────────────
# LUTs: average ASIC logic absorbed by a LUT of N inputs.
# CARRY8: 8 bits of carry-chain (MUXCY/XORCY) beyond what the LUTs hold.
# DSP48E2: a 27x18 multiplier slice; a 32x32 multiply tiles ~4 slices and is
#          ~8-10 kGE in ASIC, so ~2.5 kGE per slice actually used.
# Distributed RAM / SRL: implemented as flop arrays + read mux in ASIC.
GE_PER_PRIM = {
    "LUT1": 1.0, "LUT2": 2.0, "LUT3": 3.5, "LUT4": 5.0, "LUT5": 7.0, "LUT6": 9.0,
    "FDRE": 6.0, "FDSE": 6.0, "FDCE": 6.5, "FDPE": 6.5,
    "LDCE": 4.5, "LDPE": 4.5,
    "CARRY4": 10.0, "CARRY8": 20.0,
    "MUXF7": 2.5, "MUXF8": 2.5, "MUXF9": 2.5,
    "DSP48E1": 2500.0, "DSP48E2": 2500.0, "DSP58": 3000.0,
    "RAMD32": 200.0, "RAMS32": 200.0, "RAMD64E": 400.0, "RAMS64E": 400.0,
    "SRL16E": 100.0, "SRLC32E": 200.0,
}

# Block memories are reported as SRAM bits, not gates.
SRAM_BITS_PER_PRIM = {
    "RAMB18E1": 18 * 1024, "RAMB18E2": 18 * 1024,
    "RAMB36E1": 36 * 1024, "RAMB36E2": 36 * 1024,
    "FIFO18E1": 18 * 1024, "FIFO18E2": 18 * 1024,
    "FIFO36E1": 36 * 1024, "FIFO36E2": 36 * 1024,
    "URAM288": 288 * 1024,
}

# Fallback when the Primitives table is missing: per summary-row factors.
GE_PER_SUMMARY = {"LUT as Logic": 7.0, "CLB Registers": 6.0, "CARRY8": 20.0,
                  "CARRY4": 10.0, "DSPs": 2500.0}

# ── Process nodes ────────────────────────────────────────────────────────────
# node_nm: (label, NAND2 X1 cell um^2, HD SRAM bitcell um^2, FO4 ps)
# TSMC-class HD libraries. NAND2 is the real cell footprint, ~1.5x larger than
# 4 / (marketing MTr/mm^2), which assumes ideal NAND2/scan-FF density.
# FO4 is a practical typical-corner delay including local wire load, scaled
# between nodes by foundry speed-gain claims (N16 -> N3 ~0.56x).
NODES = {
    3:  ("N3",  0.030, 0.0210, 10.1),
    5:  ("N5",  0.040, 0.0210, 11.3),
    6:  ("N6",  0.055, 0.0270, 12.8),
    7:  ("N7",  0.065, 0.0270, 13.0),
    10: ("N10", 0.110, 0.0420, 15.7),
    12: ("N12", 0.180, 0.0740, 17.0),
    16: ("N16", 0.200, 0.0740, 18.0),
    22: ("N22", 0.350, 0.1100, 23.0),
    28: ("N28", 0.490, 0.1270, 27.0),
}

# ── Frequency model ──────────────────────────────────────────────────────────
# FO4 delays per FPGA logic level on the critical path, as ASIC logic.
FO4_PER_LEVEL = {
    "LUT1": 1.0, "LUT2": 1.5, "LUT3": 2.0, "LUT4": 2.0, "LUT5": 2.0, "LUT6": 2.0,
    "CARRY4": 1.0, "CARRY8": 2.0,
    "MUXF7": 0.5, "MUXF8": 0.5, "MUXF9": 0.5,
    "DSP48E1": 25.0, "DSP48E2": 25.0, "DSP58": 25.0,
}
FO4_DEFAULT_LEVEL = 2.0
FO4_FLOP_OVERHEAD = 4.0     # clk->q + setup
ASIC_SPEEDUP = 3.4          # ASIC vs FPGA at the same node (Kuon & Rose)
SS_DERATE = 1.35            # typical -> slow-corner signoff

# FPGA device prefix -> process node (nm).
FPGA_NODES = [
    (r"^xc(ku|vu|zu)\d+p", 16),   # UltraScale+
    (r"^xczu", 16),
    (r"^xc(ku|vu)\d+", 20),       # UltraScale
    (r"^xc7", 28),                 # 7-series
    (r"^xcv[cmpeh]", 7),           # Versal
]


def node_params(nm):
    """Return (label, nand2_um2, bitcell, fo4_ps), log-interpolating if needed."""
    if nm in NODES:
        return NODES[nm]
    known = sorted(NODES)
    if not known[0] < nm < known[-1]:
        sys.exit(f"error: node {nm}nm outside table range {known[0]}-{known[-1]}nm")
    lo = max(k for k in known if k < nm)
    hi = min(k for k in known if k > nm)
    t = (math.log(nm) - math.log(lo)) / (math.log(hi) - math.log(lo))

    def interp(a, b):
        return math.exp(math.log(a) + t * (math.log(b) - math.log(a)))

    return (f"{nm}nm*",) + tuple(interp(a, b) for a, b in
                                 zip(NODES[lo][1:], NODES[hi][1:]))


# ── Report parsing ───────────────────────────────────────────────────────────
def parse_report(path):
    """Return (header dict, {section: [(name, used, avail, util)]}, primitives)."""
    header, sections, prims = {}, {}, {}
    section = None
    with open(path) as fh:
        lines = fh.read().splitlines()

    for i, line in enumerate(lines):
        m = re.match(r"\|\s*(Design|Device|Design State)\s*:\s*(.+)$", line)
        if m:
            header[m.group(1)] = m.group(2).strip()
            continue
        # Section titles are "N. TITLE" underlined with dashes.
        if i + 1 < len(lines) and re.match(r"^\d+(\.\d+)*\.\s+\S", line) \
                and re.match(r"^-+$", lines[i + 1]):
            section = re.sub(r"^\d+(\.\d+)*\.\s+", "", line).strip()
            continue
        if not line.startswith("|") or section is None:
            continue
        cells = [c for c in line.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        name = cells[0].rstrip()
        stripped = name.strip()
        if stripped in ("Site Type", "Ref Name", "Total"):
            continue
        if section == "Primitives":
            try:
                prims[stripped] = int(cells[1])
            except ValueError:
                pass
            continue
        try:
            used = int(cells[1])
        except ValueError:
            continue
        avail = cells[4].strip() if len(cells) > 4 else ""
        util = cells[5].strip() if len(cells) > 5 else ""
        sections.setdefault(section, []).append((name, used, avail, util))
    return header, sections, prims


def parse_timing(path):
    """Return the worst setup path of a report_timing_summary file, or None."""
    with open(path) as fh:
        text = fh.read()
    m = re.search(r"^Slack \((?:VIOLATED|MET)\)\s*:\s*(-?[\d.]+)ns.*?"
                  r"Source:\s+(\S+).*?Destination:\s+(\S+).*?"
                  r"Requirement:\s+([\d.]+)ns.*?"
                  r"Data Path Delay:\s+([\d.]+)ns.*?"
                  r"Logic Levels:\s+(\d+)\s*(?:\(([^)]*)\))?",
                  text, re.S | re.M)
    if not m:
        return None
    levels = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", m.group(7) or "")}
    return {"slack": float(m.group(1)), "source": m.group(2),
            "dest": m.group(3), "period": float(m.group(4)),
            "delay": float(m.group(5)), "n_levels": int(m.group(6)),
            "levels": levels}


def fpga_node(device):
    for pat, nm in FPGA_NODES:
        if re.match(pat, device or ""):
            return nm
    return None


# ── Estimation ───────────────────────────────────────────────────────────────
def estimate(sections, prims):
    """Return ([(name, count, ge_each, ge_total)], sram_bits, unknown prims)."""
    rows, sram_bits, unknown = [], 0, []
    if prims:
        for name, cnt in sorted(prims.items(), key=lambda kv: -kv[1]):
            if name in SRAM_BITS_PER_PRIM:
                sram_bits += cnt * SRAM_BITS_PER_PRIM[name]
            elif name in GE_PER_PRIM:
                rows.append((name, cnt, GE_PER_PRIM[name], cnt * GE_PER_PRIM[name]))
            elif cnt:
                unknown.append(name)
        # RAMB36 tiles also count their inner RAMB18 halves in some reports;
        # Primitives lists leaf cells only, so no double counting here.
    else:
        flat = {n.strip().rstrip("*"): u for rows_ in sections.values()
                for n, u, _, _ in rows_}
        for name, ge in GE_PER_SUMMARY.items():
            if flat.get(name):
                rows.append((name, flat[name], ge, flat[name] * ge))
        sram_bits = flat.get("RAMB36/FIFO", 0) * 36 * 1024 \
            + flat.get("RAMB18", 0) * 18 * 1024 + flat.get("URAM", 0) * 288 * 1024
    return rows, sram_bits, unknown


def fmt_int(n):
    return f"{n:,.0f}"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", nargs="?",
                    default=os.path.join(here, "vivado", "post_synth_util.rpt"),
                    help="Vivado report_utilization file")
    ap.add_argument("--nodes", type=int, nargs="+", default=[3, 5, 6, 9, 16],
                    help="process nodes in nm (default: 3 5 6 9 16)")
    ap.add_argument("--util", type=float, default=0.70,
                    help="standard-cell placement utilization (default 0.70)")
    ap.add_argument("--sram-eff", type=float, default=0.50,
                    help="SRAM macro array efficiency, bitcell/macro area (default 0.50)")
    ap.add_argument("--timing",
                    help="Vivado report_timing_summary file for the frequency "
                         "estimate (default: *_timing.rpt next to the util report)")
    args = ap.parse_args()
    if args.timing is None:
        guess = re.sub(r"_util\.rpt$", "_timing.rpt", args.report)
        args.timing = guess if guess != args.report else None

    node_rows = [node_params(nm) for nm in args.nodes]   # validate early
    if not os.path.isfile(args.report):
        sys.exit(f"error: report not found: {args.report}")
    header, sections, prims = parse_report(args.report)

    print(f"Report : {args.report}")
    for k in ("Design", "Device", "Design State"):
        if k in header:
            print(f"{k:<12}: {header[k]}")

    # ── Utilization ──
    print("\nFPGA resource utilization")
    print(f"  {'Resource':<30} {'Used':>8} {'Available':>10} {'Util%':>7}")
    for sec in ("CLB Logic", "BLOCKRAM", "ARITHMETIC"):
        for name, used, avail, util in sections.get(sec, []):
            if used or not name.startswith(" "):
                print(f"  {name:<30} {used:>8} {avail:>10} {util:>7}")

    # ── Gate count ──
    rows, sram_bits, unknown = estimate(sections, prims)
    total_ge = sum(r[3] for r in rows)
    src = "primitives" if prims else "summary (no Primitives table)"
    print(f"\nASIC gate-count estimate (NAND2-equivalent, from {src})")
    print(f"  {'Primitive':<12} {'Count':>8} {'GE/each':>8} {'GE':>12} {'Share':>7}")
    for name, cnt, ge, tot in rows:
        share = 100.0 * tot / total_ge if total_ge else 0.0
        print(f"  {name:<12} {cnt:>8} {ge:>8.1f} {fmt_int(tot):>12} {share:>6.1f}%")
    print(f"  {'Total logic':<12} {'':>8} {'':>8} {fmt_int(total_ge):>12}"
          f"   ({total_ge / 1e3:,.1f} kGE)")
    if sram_bits:
        print(f"  Block SRAM   {fmt_int(sram_bits)} bits ({sram_bits / 8 / 1024:,.1f} KiB)")
    if unknown:
        print(f"  Not counted (no GE factor): {', '.join(unknown)}")

    # ── Area per node ──
    print(f"\nASIC area estimate (placement util {args.util:.0%}, "
          f"SRAM macro eff {args.sram_eff:.0%})")
    print(f"  {'Node':<6} {'NAND2 um2':>10} {'Logic mm2':>10} "
          f"{'SRAM mm2':>9} {'Total mm2':>10}")
    for label, nand2_um2, bitcell, _ in node_rows:
        logic_mm2 = total_ge * nand2_um2 / args.util / 1e6
        sram_mm2 = sram_bits * bitcell / args.sram_eff / 1e6
        print(f"  {label:<6} {nand2_um2:>10.4f} {logic_mm2:>10.4f} "
              f"{sram_mm2:>9.4f} {logic_mm2 + sram_mm2:>10.4f}")
    if any(nm not in NODES for nm in args.nodes):
        print("  * not a standard foundry node; log-interpolated between neighbours")

    # ── Frequency per node ──
    if not args.timing or not os.path.isfile(args.timing):
        print(f"\nNo timing report{' at ' + args.timing if args.timing else ''};"
              " skipping frequency estimate (use --timing)")
        return
    path = parse_timing(args.timing)
    if path is None:
        print(f"\nNo setup path found in {args.timing}; skipping frequency estimate")
        return
    fo4 = FO4_FLOP_OVERHEAD + sum(
        n * FO4_PER_LEVEL.get(cell, FO4_DEFAULT_LEVEL)
        for cell, n in path["levels"].items())
    lvl = " ".join(f"{k}={v}" for k, v in path["levels"].items())
    fpga_ns = path["delay"]
    print(f"\nASIC clock frequency estimate (worst FPGA path, {args.timing})")
    print(f"  Path   : {path['source']} -> {path['dest']}")
    print(f"  FPGA   : {fpga_ns:.3f} ns data path, {path['n_levels']} levels"
          f" ({lvl}), Fmax ~{1e3 / fpga_ns:.0f} MHz"
          f" (target {1e3 / path['period']:.0f} MHz, slack {path['slack']:.3f} ns)")
    print(f"  ASIC   : ~{fo4:.0f} FO4 incl. {FO4_FLOP_OVERHEAD:.0f} FO4 flop overhead")

    dev_nm = fpga_node(header.get("Device"))
    if dev_nm is not None:
        dev_fo4 = node_params(dev_nm)[3]
        print(f"  Ratio  : FPGA is {dev_nm}nm; ASIC {ASIC_SPEEDUP}x faster at same node")
    else:
        print("  Ratio  : unknown FPGA node; ratio method skipped")
    print(f"  {'Node':<6} {'FO4 ps':>7} {'Path ns':>8} {'Fmax TT':>9} "
          f"{'Fmax SS (ratio-FO4)':>21}")
    for label, _, _, fo4_ps in node_rows:
        tt_ns = fo4 * fo4_ps / 1e3
        ss_fo4 = 1e3 / (tt_ns * SS_DERATE)
        if dev_nm is not None:
            ss_ratio = 1e3 / (fpga_ns / ASIC_SPEEDUP * fo4_ps / dev_fo4)
            lo, hi = sorted((ss_ratio, ss_fo4))
            rng = f"{lo:.0f}-{hi:.0f} MHz"
        else:
            rng = f"{ss_fo4:.0f} MHz"
        print(f"  {label:<6} {fo4_ps:>7.1f} {tt_ns:>8.2f} {1e3 / tt_ns:>5.0f} MHz"
              f" {rng:>21}")
    print(f"  TT = typical corner (FO4 method); SS = slow-corner signoff "
          f"(TT / {SS_DERATE}). Pipelining unchanged.")


if __name__ == "__main__":
    main()
