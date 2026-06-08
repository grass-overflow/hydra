#!/usr/bin/env bash
set -e

echo "Starting Comprehensive Hydra Benchmark Suite..."
echo "Configuration: 2 Iterations | 90s Duration | 60s Cooldown | 25 RPS"

echo "==================== CPU CHAOS ====================" > full_results.txt
python3 -u scripts/run_live_benchmark.py --chaos cpu --iterations 2 --duration 90 --cooldown 60 --rps 25 --sla-latency 500 | tee -a full_results.txt

echo -e "\n\n==================== MEMORY CHAOS ====================" >> full_results.txt
python3 -u scripts/run_live_benchmark.py --chaos memory --iterations 2 --duration 90 --cooldown 60 --rps 25 --sla-latency 500 | tee -a full_results.txt

echo -e "\n\n==================== NETWORK CHAOS ====================" >> full_results.txt
python3 -u scripts/run_live_benchmark.py --chaos network --iterations 2 --duration 90 --cooldown 60 --rps 25 --sla-latency 500 | tee -a full_results.txt

echo "All benchmarks completed."
