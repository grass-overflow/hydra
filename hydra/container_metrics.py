import time
import os
from prometheus_client.core import GaugeMetricFamily, REGISTRY

class CgroupCpuCollector(object):
    def __init__(self):
        self.cpu_path = "/sys/fs/cgroup/cpu.stat"
        self.last_time = time.time()
        self.last_usage = self._get_usage()

    def _get_usage(self):
        try:
            with open(self.cpu_path, 'r') as f:
                for line in f:
                    if line.startswith('usage_usec'):
                        return int(line.split()[1])
        except Exception:
            return 0
        return 0

    def collect(self):
        current_usage = self._get_usage()
        current_time = time.time()
        
        delta_usage = current_usage - self.last_usage
        delta_time = (current_time - self.last_time) * 1000000 # Convert sec to usec
        
        cpu_percent = 0.0
        if delta_time > 0:
            cpu_percent = (delta_usage / delta_time) * 100

        # Update baselines for next scrape
        self.last_usage = current_usage
        self.last_time = current_time

        # Yield the metric to Prometheus
        yield GaugeMetricFamily('hydra_container_cpu_usage_percent', 
                                'CPU usage based on cgroups', 
                                value=cpu_percent)

class CgroupMemoryCollector(object):
    def __init__(self):
        # Paths for Cgroup v2 (Preferred)
        self.v2_path = "/sys/fs/cgroup/memory.current"
        self.v2_limit = "/sys/fs/cgroup/memory.max"
        
        # Paths for Cgroup v1 (Fallback)
        self.v1_path = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
        self.v1_limit = "/sys/fs/cgroup/memory/memory.limit_in_bytes"

    def collect(self):
        usage = 0
        limit = 0
        
        # 1. Try Cgroup v2 first
        if os.path.exists(self.v2_path):
            with open(self.v2_path, 'r') as f:
                usage = int(f.read().strip())
            with open(self.v2_limit, 'r') as f:
                raw_limit = f.read().strip()
                # 'max' means no limit set in K8s
                limit = int(raw_limit) if raw_limit != 'max' else 0
        
        # 2. Fallback to Cgroup v1
        elif os.path.exists(self.v1_path):
            with open(self.v1_path, 'r') as f:
                usage = int(f.read().strip())
            with open(self.v1_limit, 'r') as f:
                limit = int(f.read().strip())

        # Yield metrics to Prometheus
        usage = round(usage / (10 ** 6), 3)
        yield GaugeMetricFamily('hydra_container_memory_usage_mb', 
                                'Current container memory usage in megabytes', 
                                value=usage)
        
        if limit > 0:
            yield GaugeMetricFamily('hydra_container_memory_limit_bytes', 
                                    'Container memory limit in bytes', 
                                    value=limit)
            
            # Bonus: Calculate Percentage immediately
            percent = (usage / limit) * 100
            yield GaugeMetricFamily('hydra_container_memory_usage_percent', 
                                    'Memory usage percentage of limit', 
                                    value=percent)

