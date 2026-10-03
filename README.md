# scripts

A grab-bag of personal utility scripts.

## disk_usage.sh
Check local home filesystem usage and VS Code server footprint.

## vm_disk_usage.sh
Same as above, but run over SSH against the `vm` host. Requires `vm` to be configured in your SSH config.

## setup_vcs.csh
csh/tcsh-only. `source` it to set up the Synopsys VCS environment (`VCS_HOME`, `PATH`, license server).

## log_meal.py
Append a timestamped meal entry to `~/meal_log.csv`. Usage: `log_meal.py "sandwich and chips"`.

## vivado_ppa.py
Estimate ASIC PPA from Vivado reports. Parses a `report_utilization` file, converts the FPGA primitive counts to NAND2-equivalent gates and projects silicon area across several process nodes; if a matching `report_timing_summary` file is present it also estimates the ASIC clock frequency of the worst FPGA path. An early architecture estimate (expect ±30-50%), not a synthesis result. Usage: `vivado_ppa.py [report.rpt] [--nodes 3 5 6 9 16] [--util 0.7] [--timing post_route_timing.rpt]`.
