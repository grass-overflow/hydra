# Project HYDRA: Empirical Performance Evaluation & Benchmarking

This report provides the detailed mathematical and experimental foundation for the performance claims documented in the Project HYDRA system. It bridges the gap between high-level architectural metrics and physical cluster measurements, supplying concrete answers to technical interview questions.

---

## 1. Experimental Methodology & Workload Specification

To ensure statistical rigor and eliminate testing bias, Project HYDRA utilizes a custom-built, automated benchmarking harness (`scripts/run_live_benchmark.py`). This harness orchestrates a live comparison between the native Kubernetes Horizontal Pod Autoscaler (HPA) and the custom PPO-based Reinforcement Learning (RL) controller.

### Workload Configuration
| Dimension | Specification |
|:---|:---|
| **Load Generator** | **Grafana k6** running a `constant-arrival-rate` executor. |
| **Traffic Rate** | **20-25 Requests Per Second (RPS)** representing a steady state of HTTP traffic hitting the backend API. |
| **Chaos Injection** | **Chaos Mesh** dynamically injects transient failure states (e.g., CPU stress on 1 core at 80% load, Memory Leaks, Network Delays) directly into the application pods to simulate real-world production degradation. |
| **SLA Latency** | **500.0 ms**. Any response exceeding this threshold is categorized as an SLA violation. |
| **Test Iterations** | Benchmarks are executed across multiple statistical iterations to compute sample means and standard deviations (N-1). |
| **Measurement Windows** | 120s of Chaos Injection followed by 120s of Cooldown Phase tracking scale-down response. |

---

## 2. Experimental Observations & Limitations

While initial synthetic testing showed massive theoretical improvements, rigorous live cluster evaluation revealed a much more complex reality, exposing critical limitations in both native heuristics and raw PPO policies.

### 2.1. CPU Chaos Over-Scaling
During severe CPU starvation, HPA struggled to react quickly due to its 15-60s aggregation delay. The RL agent responded much faster, scaling up aggressively (`3 -> 4 -> 5 -> 6 -> 7 pods`). However, the agent's reward function prioritized latency suppression so heavily that it incurred a **~67% higher resource cost** than HPA (`385 pod-s` vs `230 pod-s`). The agent traded resource efficiency for SLA preservation.

### 2.2. Network Chaos and Policy Generalization Failure
Under network-induced latency (where CPU remains low but HTTP requests time out), the PPO policy exhibited a critical generalization failure. The agent observed high latency but low CPU utilization. Having learned that `low CPU = idle state`, it actively **scaled down** replicas during the degradation event (`2 -> 1 pod`), exacerbating the outage. This highlighted a fundamental limitation: the policy failed to distinguish between network-induced latency and lack-of-load latency without explicit network I/O features in its state vector.

### 2.3. TTR Capping and Cooldown Measurement
* **TTR (Time to Recovery):** In several extreme starvation scenarios, the system failed to reach the strict recovery criteria (`Ready Replicas == Desired`, `p95 < 500ms`, `Error Rate < 5%`) within the 90-second observation window. In these cases, TTR is hard-capped at 90s, indicating a complete failure to recover during the test window.
* **Cooldown Measurement:** The benchmark initially flagged cooldown recovery if replicas were `<= 2`. If an agent never successfully scaled up beyond 2 replicas during a failure, it immediately registered a `0.0s` cooldown upon entering the recovery phase, which mathematically distorted the scale-down latency statistics.

---

## 3. Time To Recovery (TTR) Formulation

TTR is defined rigorously via a sliding 10-second window function in `run_live_benchmark.py`. The system is only considered "recovered" when:
1. `Ready Replicas == Desired Replicas` (Physical Stability)
2. `p95 Latency < 500ms` (SLA Compliance)
3. `Error Rate < 5%` (Functional Health)

By mathematically requiring all three conditions to be met for consecutive sliding windows, the benchmark prevents false-positive recovery signals that occur during transient latency dips.

---

## 4. Telemetry Mechanics: Bypassing Metrics Server for Control

While Metrics Server remains deployed for general cluster operations, the RL control plane bypasses it entirely to consume telemetry directly:

1. **Direct Kubernetes API Queries:** Instead of relying on `kube-state-metrics` (which introduces aggregation lag), the RL agent uses the Python Kubernetes client to query `AppsV1Api` for live `spec.replicas` and `status.ready_replicas`.
2. **Normalized Prometheus Telemetry:** The FastAPI server records request durations in milliseconds. The custom `MetricsCollector` retrieves these via PromQL and explicitly normalizes them into seconds (`avg_lat_ms / 1000.0`), aligning perfectly with the continuous boundary spaces expected by the trained Neural Network. 
3. **Cgroup Interface Fallbacks:** The application pods still export raw cgroup statistics (CPU and Memory) directly to Prometheus, bypassing the Kubelet completely and allowing the RL Agent to achieve near-real-time telemetry with 5-second scrape intervals.

---

## 5. Final Resume Impact Statement

When summarizing this project for technical portfolios or interviews, focusing on the architecture and the empirical insights (rather than inflated percentages) provides a heavily defensible, senior-level engineering claim:

> *"Developed and evaluated a PPO-based Kubernetes resilience controller under CPU, memory, and network fault injection using Chaos Mesh and Prometheus telemetry. Experimental results demonstrated improved recovery behavior under selected failure modes and highlighted limitations of RL policies under network-induced degradation."*

---

## 6. Reinforcement Learning Formulation

A critical aspect of the system's defensibility is how the PPO agent understands the cluster state and the actions it is permitted to take. 

### 9-Dimensional State Vector
The observation space is a continuous vector normalized for the neural network:
`[healthy_flag, degraded_flag, crashed_flag, cpu_usage, memory_usage, latency_seconds, error_rate, time_since_failure, active_replicas]`

### Discrete Action Space
The controller translates the PPO policy's discrete output into physical Kubernetes operations:
* `Action 0`: **No-Op** (Maintain current state)
* `Action 1`: **Restart Pod** (Kill degraded pod)
* `Action 2`: **Scale Up** (+1 Replica)
* `Action 3`: **Scale Down** (-1 Replica)

---


