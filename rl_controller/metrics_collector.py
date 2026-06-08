import requests
import json
import logging
import numpy as np
from kubernetes import client, config as k8s_config

logger = logging.getLogger("MetricsCollector")
logging.basicConfig(level=logging.INFO)

class MetricsCollector:
    def __init__(self, prometheus_url: str, namespace: str, deployment_name: str, max_pods: int, max_steps: int):
        self.prometheus_url = prometheus_url
        self.namespace = namespace
        self.deployment_name = deployment_name
        self.max_pods = max_pods
        self.max_steps = max_steps
        self.time_since_failure = 0
        
        # Load kubernetes configuration to query replica states directly
        try:
            k8s_config.load_incluster_config()
        except Exception:
            try:
                k8s_config.load_kube_config()
            except Exception:
                pass
        self.apps_v1 = client.AppsV1Api()
        
    def _query(self, query: str, default_val: float = 0.0) -> float:
        try:
            resp = requests.get(f"{self.prometheus_url}/api/v1/query", params={'query': query}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get('data', {}).get('result', [])
                if results and 'value' in results[0]:
                    val = results[0]['value'][1]
                    if val == 'NaN' or val is None:
                        return default_val
                    return float(val)
        except Exception as e:
            logger.warning(f"Error querying Prometheus for '{query}': {e}")
        return default_val

    def get_state(self) -> np.ndarray:
        # Replicas & Health: Query K8s API directly instead of relying on missing kube-state-metrics
        replicas = 1.0
        healthy = 0.0
        try:
            deploy = self.apps_v1.read_namespaced_deployment(self.deployment_name, self.namespace)
            replicas = float(deploy.spec.replicas or 1.0)
            healthy = float(deploy.status.ready_replicas or 0.0)
        except Exception as e:
            logger.warning(f"K8s API replicas query failed: {e}. Falling back to default.")
            
        crashed = max(0.0, replicas - healthy)
        
        # cpu & mem from hydra application export endpoints via Prometheus
        q_cpu = 'avg(hydra_container_cpu_usage_percent) / 100.0'
        # memory limit normalization to 300MB
        q_mem = 'avg(hydra_container_memory_usage_mb) / 300.0'
        
        avg_cpu = self._query(q_cpu, default_val=0.1)
        avg_mem = self._query(q_mem, default_val=0.1)
        
        # latency: convert to seconds (the model is trained expecting latency in seconds)
        # Note: server.py observes latency in milliseconds (e.g. 250.0). We must divide by 1000.0 to convert to seconds.
        q_lat = f'sum(rate(hydra_http_request_duration_seconds_sum[1m])) / sum(rate(hydra_http_request_duration_seconds_count[1m]))'
        avg_lat_ms = self._query(q_lat, default_val=50.0) # Default 50ms
        avg_lat = avg_lat_ms / 1000.0 # Convert to seconds
        
        # error from nginx
        q_err = f'sum(rate(nginx_ingress_controller_requests{{status=~"5..", namespace="{self.namespace}"}}[1m])) / sum(rate(nginx_ingress_controller_requests{{namespace="{self.namespace}"}}[1m]))'
        avg_err = self._query(q_err, default_val=0.001)

        degraded = 0.0
        if avg_cpu > 0.9 or avg_mem > 0.9 or avg_lat > 1.0 or avg_err > 0.05:
            degraded = healthy 
            healthy = 0.0

        if crashed > 0 or degraded > 0:
            self.time_since_failure = 0
        else:
            self.time_since_failure += 1

        state = np.array([
            healthy,
            degraded,
            crashed,
            avg_cpu,
            avg_mem,
            avg_lat / 1.0, # normalized based on 1.0 second limit scaling
            avg_err,
            min(1.0, self.time_since_failure / self.max_steps),
            min(1.0, replicas / self.max_pods)
        ], dtype=np.float32)
        
        state = np.clip(state, 0.0, 100.0) 
        return list(state.astype(float))
