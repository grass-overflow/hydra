# Project Hydra: RL-Driven Self-Healing Kubernetes

## Overview
Integrated a **Proximal Policy Optimization (PPO)** Reinforcement Learning Neural Network directly into a physical Kubernetes cluster to natively orchestrate scale testing and anomaly remediation.

All standard Kubernetes native automation elements (HorizontalPodAutoscalers, LivenessProbes, ReadinessProbes) have been intentionally silenced. The cluster's life and death relies **100%** on the decisions of the RL Agent checking state configurations every 30 seconds.

---

## Setup

1. **Start Minikube**
   ```bash
   minikube start
   ```
2. **Connect the Native Image Builder**
   ```bash
   eval $(minikube docker-env)
   ```
3. **Setup Chaos Mesh & Ingress** (Installs anomaly injectors)
   ```bash
   chmod +x setup.sh && ./setup.sh
   ```
4. **Build the RL Model**
   Builds the RL Model encapsulating `ppo_kubernetes_hardened.zip`.
   ```bash
   chmod +x build.sh && ./build.sh
   ```
5. **Launch**
   Applies the cluster configuration, deploying target services, Grafana, and the Python RL Poller.
   ```bash
   chmod +x start.sh && ./start.sh
   ```
---

### Observations
<img width="1920" height="1080" alt="Screenshot from 2026-04-05 02-53-08" src="https://github.com/user-attachments/assets/58a26031-47c5-4411-912f-7a67d1462289" />

[Screencast from 2026-04-05 02-53-44.webm](https://github.com/user-attachments/assets/2cc28d00-6e59-4d70-a3c9-87f581dfb486)
