from kubernetes import client, config
import random
import logging

logger = logging.getLogger("K8sActionExecutor")
logging.basicConfig(level=logging.INFO)

class K8sActionExecutor:
    def __init__(self, namespace: str, deployment_name: str, min_replicas: int, max_replicas: int):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                logger.warning("Could not load Kubernetes config. Operating in dummy mode.")
                
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        self.namespace = namespace
        self.deployment_name = deployment_name
        self.min_replicas = min_replicas
        self.max_replicas = max_replicas
        # typically the label is the deployment name without the generic "-deployment" suffix 
        self.label_selector = f"app={self.deployment_name.replace('-deployment', '')}"

    def execute_action(self, action: int) -> str:
        try:
            if action == 0:
                return "no-op"
            elif action == 1:
                return self._restart_pod()
            elif action == 2:
                return self._scale_deployment(1)
            elif action == 3:
                return self._scale_deployment(-1)
            return "invalid action"
        except Exception as e:
            logger.error(f"Failed to execute action {action}: {e}")
            return f"error: {str(e)}"

    def _restart_pod(self) -> str:
        pods = self.core_v1.list_namespaced_pod(self.namespace, label_selector=self.label_selector).items
        if not pods:
            return "no pods found to restart"
            
        target_pod = random.choice(pods).metadata.name
        self.core_v1.delete_namespaced_pod(target_pod, self.namespace)
        return f"restarted pod {target_pod}"

    def _scale_deployment(self, delta: int) -> str:
        deployment = self.apps_v1.read_namespaced_deployment(self.deployment_name, self.namespace)
        current_replicas = deployment.spec.replicas or 1
        new_replicas = current_replicas + delta
        
        if new_replicas < self.min_replicas:
            return f"scale bound check failed: cannot scale below min ({self.min_replicas})"
        if new_replicas > self.max_replicas:
            return f"scale bound check failed: cannot scale above max ({self.max_replicas})"
            
        deployment.spec.replicas = new_replicas
        self.apps_v1.patch_namespaced_deployment(self.deployment_name, self.namespace, deployment)
        return f"scaled {delta > 0 and 'up' or 'down'} from {current_replicas} to {new_replicas}"
