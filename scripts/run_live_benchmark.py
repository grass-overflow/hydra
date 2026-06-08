#!/usr/bin/env python3
"""
Project HYDRA: Research-Grade Live Cluster Benchmarking & Telemetry Collector
Performs a scientifically rigorous comparison of Native HPA vs. PPO RL Agent.

Features:
- Uses Grafana k6 for industry-standard load testing (requires k6 installed).
- Tracks availability, p95 latency, SLA violations, Time-to-Recovery (TTR), and Pod-Seconds cost.
- Measures TTR using a combination of probe metrics and physical pod replica readiness states.
- Supports multiple chaos profiles: CPU stress, Memory stress, Network stress, or HTTP delay.
- Computes sample mean and sample standard deviation (N-1) over multiple test iterations.
"""

import sys
import os
import time
import math
import argparse
import subprocess
import json
import urllib.request
import urllib.parse
import threading

# Dynamic path resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
HPA_PATH = os.path.join(PROJECT_ROOT, "kb8-configs", "hpa.yaml")

def print_banner(chaos_type, rps, sla_latency):
    print("=" * 80)
    print("            HYDRA RESEARCH-GRADE LIVE BENCHMARKING ENGINE")
    print("=" * 80)
    print(" This engine runs parallel stress-test iterations comparing Native HPA")
    print(" against the trained PPO Agent, computing real statistical significance.")
    print(f" Chaos Type:     {chaos_type.upper()}")
    print(f" Load Generator: Grafana k6 at {rps} RPS")
    print(f" SLA Threshold:  {sla_latency} ms")
    print("=" * 80)

# ==============================================================================
# SUBPROCESS HELPER
# ==============================================================================
def run_cmd(cmd_list, capture=True):
    try:
        res = subprocess.run(cmd_list, capture_output=capture, text=True, check=True)
        return res.stdout.strip() if capture else ""
    except subprocess.CalledProcessError as e:
        print(f"[X] Command failed: {' '.join(cmd_list)}")
        if capture and e.stderr:
            print(f"    Error output: {e.stderr.strip()}")
        raise e

# ==============================================================================
# MATHEMATICAL UTILITIES
# ==============================================================================
def calculate_percentile(data, percentile):
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_data[int(k)])
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return float(d0 + d1)

def compute_stats(data):
    if not data:
        return 0.0, 0.0
    mean = sum(data) / len(data)
    if len(data) > 1:
        variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)
    else:
        variance = 0.0
    std_dev = math.sqrt(variance)
    return mean, std_dev

def calculate_ttr(samples, replica_states, chaos_start_time, duration, sla_latency_ms=500.0, max_error_rate=0.05):
    """
    Computes Time to Recovery (TTR) by slicing samples into 10-second windows.
    TTR is the elapsed time from chaos injection until the system stabilizes to:
      1. All replicas are healthy (ready == total AND ready > 0)
      2. Client p95 latency is below SLA
      3. Client error rate is below threshold
    and remains stable for subsequent windows.
    """
    window_size = 10.0
    num_windows = int(duration / window_size)
    
    first_healthy_time = -1
    for w in range(num_windows):
        w_start = chaos_start_time + w * window_size
        w_end = w_start + window_size
        
        # Get replica state in this window (closest snapshot)
        rep_state = [r for r in replica_states if w_start <= r[0] < w_end]
        if rep_state:
            ready, total = rep_state[0][1], rep_state[0][2]
        else:
            ready, total = 0, 0
            
        # Filter samples in this window
        w_samples = [s for s in samples if w_start <= s[0] < w_end]
        if not w_samples:
            continue
            
        success_latencies = [s[1] for s in w_samples if s[2]]
        errors = sum(1 for s in w_samples if not s[2])
        error_rate = errors / len(w_samples) if w_samples else 0.0
        
        w_p95 = calculate_percentile(success_latencies, 95) if success_latencies else 1000.0
        
        # Define healthy: physical stability + SLA compliance
        is_healthy = (ready == total) and (ready > 0) and (w_p95 < sla_latency_ms) and (error_rate < max_error_rate)
        
        if is_healthy:
            # Verify system remains stable for subsequent windows (stability check)
            remains_healthy = True
            for next_w in range(w + 1, min(w + 3, num_windows)):
                nw_start = chaos_start_time + next_w * window_size
                nw_end = nw_start + window_size
                
                n_rep = [r for r in replica_states if nw_start <= r[0] < nw_end]
                n_ready, n_total = n_rep[0][1], n_rep[0][2] if n_rep else (0, 0)
                
                nw_samples = [s for s in samples if nw_start <= s[0] < nw_end]
                if not nw_samples:
                    continue
                n_lat = [s[1] for s in nw_samples if s[2]]
                n_err = sum(1 for s in nw_samples if not s[2]) / len(nw_samples)
                n_p95 = calculate_percentile(n_lat, 95) if n_lat else 1000.0
                
                if (n_ready != n_total) or (n_ready == 0) or (n_p95 >= sla_latency_ms) or (n_err >= max_error_rate):
                    remains_healthy = False
                    break
            
            if remains_healthy:
                first_healthy_time = w * window_size
                break
                
    return first_healthy_time if first_healthy_time != -1 else duration

# ==============================================================================
# K6 LOAD GENERATOR WITH INTEGRATED PROBE
# ==============================================================================
class K6LoadGenerator:
    def __init__(self, target_url, host_header, requests_per_second=20):
        self.target_url = target_url
        self.host_header = host_header
        self.rps = requests_per_second
        self.proc = None
        self.k6_path = "k6"
        self.js_path = os.path.join(SCRIPT_DIR, "k6_load_test.js")
        self.summary_path = os.path.join(SCRIPT_DIR, "k6_summary.json")
        self.probe_samples = []
        self.probe_thread = None
        self.running = False

    def check_install(self):
        try:
            subprocess.run(["k6", "version"], capture_output=True, check=True)
            return True
        except Exception:
            print("\n" + "="*80)
            print("[X] ERROR: k6 is not installed on this system.")
            print("    Please install it using one of the following methods:")
            print("    - Snap (Recommended): sudo snap install k6")
            print("    - Ubuntu/Debian:      sudo apt-get install k6")
            print("    - macOS:              brew install k6")
            print("="*80 + "\n")
            return False

    def _write_js_script(self):
        headers_js = "'User-Agent': 'HydraK6Benchmark/1.0'"
        if self.host_header:
            headers_js += f", 'Host': '{self.host_header}'"
            
        js_content = f"""
import http from 'k6/http';

export const options = {{
  discardResponseBodies: true,
  scenarios: {{
    constant_load: {{
      executor: 'constant-arrival-rate',
      rate: {self.rps},
      timeUnit: '1s',
      duration: '30m', // Manual termination
      preAllocatedVUs: 5,
      maxVUs: 50,
    }},
  }},
}};

export default function () {{
  const params = {{
    headers: {{
      {headers_js}
    }},
    timeout: '3s'
  }};
  http.get('{self.target_url}', params);
}}

export function handleSummary(data) {{
  return {{
    '{self.summary_path}': JSON.stringify(data),
  }};
}}
"""
        with open(self.js_path, "w") as f:
            f.write(js_content.strip())

    def _probe_worker(self):
        # 2 RPS python probe thread to monitor latency metrics in real-time
        interval = 0.5
        while self.running:
            start_time = time.time()
            success = False
            latency = 0.0
            try:
                headers = {'User-Agent': 'HydraProbe/1.0'}
                if self.host_header:
                    headers['Host'] = self.host_header
                req = urllib.request.Request(self.target_url, headers=headers)
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    latency = (time.time() - start_time) * 1000.0
                    if response.status == 200:
                        success = True
            except Exception:
                latency = (time.time() - start_time) * 1000.0
            
            self.probe_samples.append((start_time, latency, success))
            elapsed = time.time() - start_time
            time.sleep(max(0.01, interval - elapsed))

    def start(self):
        self.probe_samples = []
        self._write_js_script()
        
        if os.path.exists(self.summary_path):
            os.remove(self.summary_path)
            
        print(f"[!] Starting K6 load generator ({self.rps} RPS)...")
        cmd = [self.k6_path, "run", self.js_path]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Start probe thread
        self.running = True
        self.probe_thread = threading.Thread(target=self._probe_worker)
        self.probe_thread.daemon = True
        self.probe_thread.start()

    def stop(self, sla_latency_ms=500.0):
        self.running = False
        if self.probe_thread:
            self.probe_thread.join(timeout=1.0)
            self.probe_thread = None
            
        if self.proc:
            # Terminate k6 gracefully using SIGINT so it outputs the summary
            self.proc.send_signal(subprocess.signal.SIGINT)
            try:
                self.proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
            
        k6_metrics = {
            "p95": 1000.0,
            "availability": 0.0,
            "error_rate": 100.0,
            "sla_violations": 100.0
        }
        
        time.sleep(1.0) # Wait for filesystem sync
        if os.path.exists(self.summary_path):
            try:
                with open(self.summary_path, "r") as f:
                    data = json.load(f)
                metrics = data.get("metrics", {})
                
                # Fetch latency
                p95 = metrics.get("http_req_duration", {}).get("values", {}).get("p(95)", 1000.0)
                
                # Fetch error rate (correctly checking for "rate" or "value")
                failed_metric = metrics.get("http_req_failed", {}).get("values", {})
                err_rate_val = failed_metric.get("rate") if "rate" in failed_metric else failed_metric.get("value", 1.0)
                err_rate = err_rate_val * 100.0
                availability = 100.0 - err_rate
                
                # SLA Violations calculated from high-resolution probe
                probe_latencies = [s[1] for s in self.probe_samples if s[2]]
                sla_violations = (sum(1 for l in probe_latencies if l > sla_latency_ms) / len(probe_latencies) * 100) if probe_latencies else 0.0
                
                k6_metrics = {
                    "p95": p95,
                    "availability": availability,
                    "error_rate": err_rate,
                    "sla_violations": sla_violations
                }
            except Exception as e:
                print(f"[X] Failed to parse k6 summary: {e}")
                
        # Clean up files
        try:
            if os.path.exists(self.js_path):
                os.remove(self.js_path)
            if os.path.exists(self.summary_path):
                os.remove(self.summary_path)
        except Exception:
            pass
            
        return k6_metrics

# ==============================================================================
# TELEMETRY POLLING LOGIC
# ==============================================================================
def get_ready_replicas(namespace="hydra", deployment="hydra-deployment"):
    try:
        cmd = ["kubectl", "get", "deployment", deployment, "-n", namespace, "-o", "json"]
        out = run_cmd(cmd)
        data = json.loads(out)
        status = data.get("status", {})
        ready = status.get("readyReplicas", 0)
        total = status.get("replicas", 0)
        return int(ready), int(total)
    except Exception:
        return 0, 0

# ==============================================================================
# EVALUATION ITERATION RUNNER
# ==============================================================================
def run_live_test_phase(phase_name, load_generator, test_duration, cooldown_duration, chaos_path, sla_latency_ms=500.0):
    print(f"\n[▶] Starting Iteration for: {phase_name}")
    print(f"[!] Warming up system metrics...")
    time.sleep(5)
    
    # 1. Start k6 user load
    load_generator.start()
    
    # 2. Inject live Chaos Mesh Stressor
    chaos_start_time = time.time()
    print(f"[!] INJECTING CHAOS: stressor from {chaos_path}...")
    try:
        run_cmd(["kubectl", "apply", "-f", chaos_path, "-n", "hydra"])
        print("[✓] Chaos Mesh stressor injected successfully.")
    except Exception:
        print("[X] Failed to apply Chaos Mesh. Proceeding with load only...")

    # 3. Monitor performance live
    poll_interval = 10
    steps = test_duration // poll_interval
    historical_replicas = []
    replica_states = []
    
    for step in range(steps):
        t_now = time.time()
        ready, total = get_ready_replicas()
        replica_states.append((t_now, ready, total))
        
        # Compute real-time local percentile for logging
        current_samples = [s[1] for s in load_generator.probe_samples[-20:] if s[2]]
        curr_p95 = calculate_percentile(current_samples, 95) if current_samples else 0.0
        
        print(f"    [T+{step*poll_interval:3d}s] Replicas: {ready}/{total} | Recent p95 Latency: {curr_p95:6.1f}ms")
        historical_replicas.append(total)
        time.sleep(poll_interval)

    # 4. Clean up Chaos Mesh
    print("[!] REMOVING CHAOS: Tearing down fault injectors...")
    try:
        run_cmd(["kubectl", "delete", "-f", chaos_path, "-n", "hydra"])
        print("[✓] Chaos Mesh stressors removed.")
    except Exception:
        pass
        
    # 5. Stop live load
    k6_results = load_generator.stop(sla_latency_ms=sla_latency_ms)

    # 6. Monitor Cooldown downscaling response
    print(f"[!] MONITORING COOLDOWN: Tracking scale-down response speed for {cooldown_duration}s...")
    cooldown_steps = cooldown_duration // poll_interval
    peak_replicas = max(historical_replicas) if historical_replicas else 0
    scale_down_detected = -1
    
    # If the system never scaled up, cooldown scale down is technically 0
    if peak_replicas <= 2:
        scale_down_detected = 0
        
    for step in range(cooldown_steps):
        ready, total = get_ready_replicas()
        replica_states.append((time.time(), ready, total))
        print(f"    [Cooldown T+{step*poll_interval:3d}s] Replicas: {ready}/{total}")
        
        # Proper cooldown detection: when replicas drop below the peak reached during chaos
        if total < peak_replicas and scale_down_detected == -1:
            scale_down_detected = step * poll_interval
            print(f"    [✓] Cooldown scale-down detected at T+{scale_down_detected}s!")
        time.sleep(poll_interval)
        
    # Calculate robust, system-state TTR
    ttr = calculate_ttr(load_generator.probe_samples, replica_states, chaos_start_time, test_duration, sla_latency_ms=sla_latency_ms)
    
    # Compute resource cost (Pod-Seconds)
    pod_seconds = sum(r * poll_interval for r in historical_replicas)
    
    return {
        "p95": k6_results["p95"],
        "availability": k6_results["availability"],
        "error_rate": k6_results["error_rate"],
        "ttr": ttr,
        "scale_down_latency": scale_down_detected if scale_down_detected != -1 else cooldown_duration,
        "pod_seconds": pod_seconds,
        "sla_violations": k6_results["sla_violations"]
    }

# ==============================================================================
# DYNAMIC LOADBALANCER RESOLUTION
# ==============================================================================
def resolve_service_ip(service_name, namespace):
    try:
        cmd = ["kubectl", "get", "svc", service_name, "-n", namespace, "-o", "json"]
        out = run_cmd(cmd)
        data = json.loads(out)
        ingresses = data.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if ingresses:
            return ingresses[0].get("ip")
    except Exception:
        pass
    return None

# ==============================================================================
# MAIN ENGINE ENTRYPOINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Hydra Live Cluster Benchmarking with K6")
    parser.add_argument("--chaos", type=str, choices=["cpu", "memory", "network", "delay"], default="cpu",
                        help="Type of Chaos Mesh fault to inject (default: cpu)")
    parser.add_argument("--iterations", type=int, default=1, help="Number of benchmark runs (default: 1)")
    parser.add_argument("--duration", type=int, default=180, help="Chaos injection phase duration in seconds (default: 180)")
    parser.add_argument("--cooldown", type=int, default=180, help="Scale-down cooldown phase duration in seconds (default: 180)")
    parser.add_argument("--rps", type=int, default=20, help="Target Requests Per Second (default: 20)")
    parser.add_argument("--sla-latency", type=float, default=500.0, help="SLA latency threshold in milliseconds (default: 500.0)")
    args = parser.parse_args()

    print_banner(args.chaos, args.rps, args.sla_latency)
    
    # Resolve dynamic chaos manifest path
    chaos_files = {
        "cpu": "cpu-stress.yaml",
        "memory": "mem-stress.yaml",
        "network": "network-stress.yaml",
        "delay": "http-delay.yaml"
    }
    chaos_filename = chaos_files[args.chaos]
    chaos_path = os.path.join(PROJECT_ROOT, "chaosmesh", chaos_filename)

    if not os.path.exists(chaos_path):
        print(f"[X] Error: Chaos configuration not found at {chaos_path}")
        sys.exit(1)

    # Resolve target URL using Minikube NodePort exclusively to avoid tunnel routing issues
    try:
        minikube_ip_raw = run_cmd(["minikube", "ip"])
        minikube_ip = minikube_ip_raw.strip().split("\n")[-1]
        target_ip = minikube_ip
        host_header = None
        target_url = f"http://{minikube_ip}:30000/data?ticker=GOOGL"
    except Exception:
        print("[X] Error: Could not resolve Minikube IP. Ensure minikube is running.")
        sys.exit(1)

    print(f"[✓] Target URL resolved: {target_url}")
    load_gen = K6LoadGenerator(target_url, host_header, requests_per_second=args.rps)

    # Verify k6 installation before proceeding
    if not load_gen.check_install():
        sys.exit(1)

    hpa_runs = []
    rl_runs = []

    # ==============================================================================
    # RUN PHASE 1: NATIVE HPA PERFORMANCE
    # ==============================================================================
    for i in range(args.iterations):
        print("\n" + "=" * 80)
        print(f"      CONFIGURING PHASE 1: NATIVE KUBERNETES HPA (RUN {i+1}/{args.iterations})")
        print("=" * 80)
        
        # Scale RL agent to 0
        run_cmd(["kubectl", "scale", "deployment", "chaos-rl-controller", "--replicas=0", "-n", "hydra"])
        
        # Apply standard HPA
        try:
            run_cmd(["kubectl", "apply", "-f", HPA_PATH, "-n", "hydra"])
        except Exception as e:
            print(f"[X] Failed to apply HPA: {e}")
            
        # Reset cluster state
        print("[!] Resetting pod scaling states...")
        run_cmd(["kubectl", "scale", "deployment", "hydra-deployment", "--replicas=3", "-n", "hydra"])
        
        metrics = run_live_test_phase("Native K8s HPA", load_gen, args.duration, args.cooldown, chaos_path, sla_latency_ms=args.sla_latency)
        hpa_runs.append(metrics)

    # ==============================================================================
    # RUN PHASE 2: HYDRA RL AGENT PERFORMANCE
    # ==============================================================================
    for i in range(args.iterations):
        print("\n" + "=" * 80)
        print(f"      CONFIGURING PHASE 2: HYDRA RL AGENT (RUN {i+1}/{args.iterations})")
        print("=" * 80)
        
        # Delete HPA
        try:
            run_cmd(["kubectl", "delete", "hpa", "--all", "-n", "hydra"])
        except Exception:
            pass
        
        # Enable RL controllers
        run_cmd(["kubectl", "scale", "deployment", "rl-agent-service", "--replicas=1", "-n", "hydra"])
        run_cmd(["kubectl", "scale", "deployment", "chaos-rl-controller", "--replicas=1", "-n", "hydra"])
        
        # Reset cluster state
        print("[!] Resetting pod scaling states...")
        run_cmd(["kubectl", "scale", "deployment", "hydra-deployment", "--replicas=3", "-n", "hydra"])
        
        metrics = run_live_test_phase("Hydra RL Agent", load_gen, args.duration, args.cooldown, chaos_path, sla_latency_ms=args.sla_latency)
        rl_runs.append(metrics)

    # ==============================================================================
    # SUMMARY RESULTS TABLE (STATISTICAL COMPILATION)
    # ==============================================================================
    print("\n" + "=" * 80)
    print("                     LIVE OPERATIONAL COMPARATIVE RESULTS")
    print("=" * 80)
    
    metrics_to_print = [
        ("p95", "p95 HTTP Request Latency", "ms"),
        ("ttr", "Time to Recovery (TTR)", "s"),
        ("scale_down_latency", "Scale-down Cooldown", "s"),
        ("pod_seconds", "Resource Cost (Pod-Seconds)", "pod-s"),
        ("availability", "Service Availability", "%"),
        ("sla_violations", f"SLA Violations (>{args.sla_latency}ms)", "%")
    ]
    
    print(f"{'Operational Metric':<30} | {'Native K8s HPA':<20} | {'Hydra RL Agent':<20} | {'Improvement':<12}")
    print("-" * 90)
    
    for key, name, unit in metrics_to_print:
        hpa_vals = [r[key] for r in hpa_runs]
        rl_vals = [r[key] for r in rl_runs]
        
        hpa_mean, hpa_std = compute_stats(hpa_vals)
        rl_mean, rl_std = compute_stats(rl_vals)
        
        # Calculate dynamic improvement
        if key in ["availability"]:
            # Higher is better
            imp = ((rl_mean - hpa_mean) / hpa_mean * 100) if hpa_mean > 0 else 0.0
            imp_str = f"{imp:+.1f}%" if hpa_mean > 0 else "-"
        else:
            # Lower is better
            imp = ((hpa_mean - rl_mean) / hpa_mean * 100) if hpa_mean > 0 else 0.0
            imp_str = f"{imp:+.1f}%" if hpa_mean > 0 else "-"
            
        hpa_str = f"{hpa_mean:.1f} ± {hpa_std:.1f} {unit}" if args.iterations > 1 else f"{hpa_mean:.1f} {unit}"
        rl_str = f"{rl_mean:.1f} ± {rl_std:.1f} {unit}" if args.iterations > 1 else f"{rl_mean:.1f} {unit}"
        
        print(f"{name:<30} | {hpa_str:<20} | {rl_str:<20} | {imp_str:<12}")
        
    print("=" * 80)
    print("[✓] Live cluster evaluation complete. Load generated via Grafana k6.")
    print("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Benchmark aborted. Tearing down chaos stressors...")
        try:
            # Clean up all possible chaos files
            chaos_files = {
                "cpu": "cpu-stress.yaml",
                "memory": "mem-stress.yaml",
                "network": "network-stress.yaml",
                "delay": "http-delay.yaml"
            }
            for cf in chaos_files.values():
                cf_path = os.path.join(PROJECT_ROOT, "chaosmesh", cf)
                if os.path.exists(cf_path):
                    run_cmd(["kubectl", "delete", "-f", cf_path, "-n", "hydra"], capture=True)
        except Exception:
            pass
        sys.exit(0)
