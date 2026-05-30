import yaml
import time
import requests
import logging
import os
from metrics_collector import MetricsCollector
from k8s_action_executor import K8sActionExecutor
from chaos_controller import ChaosController
from prometheus_client import start_http_server, Gauge

logger = logging.getLogger("ChaosRLController")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")

# expose rl actions to prom
RL_ACTION_GAUGE = Gauge('hydra_rl_last_action', 'Most recent action taken by RL Agent (0=noop, 1=restart, 2=up, 3=down)')
RL_CHAOS_GAUGE = Gauge('hydra_rl_chaos_active', 'Defines if chaos is currently injected (1) or not (0)')

def load_config():
    config_path = os.getenv("CONFIG_PATH", "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def run_loop():
    logger.info("Initializing Chaos-RL Controller components...")
    start_http_server(8001)
    logger.info("Prometheus metrics server listening on port 8001")
    
    RL_ACTION_GAUGE.set(0)
    RL_CHAOS_GAUGE.set(0)
    
    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("Configuration file config.yaml not found! Exiting.")
        return
        
    metrics = MetricsCollector(
        prometheus_url=config["prometheus_url"],
        namespace=config["namespace"],
        deployment_name=config["deployment_name"],
        max_pods=config["max_replicas"],
        max_steps=config.get("max_steps", 200)
    )
    
    executor = K8sActionExecutor(
        namespace=config["namespace"],
        deployment_name=config["deployment_name"],
        min_replicas=config["min_replicas"],
        max_replicas=config["max_replicas"]
    )
    
    
    chaos_dir = os.getenv("CHAOS_DIR", "../chaosmesh")
    chaos = ChaosController(chaos_dir=chaos_dir)
    
    observation_interval = config["observation_interval"]
    chaos_interval = config["chaos_injection_interval"]
    rl_agent_url = config["rl_agent_service_url"]
    
    last_chaos_time = time.time()
    
    # clear any previous chaos on startup to ensure clean state
    chaos.remove_chaos()
    
    logger.info("Starting master Observation-Decision-Execution loop...")
    while True:
        try:
            loop_start = time.time()
            
            # observe
            state = metrics.get_state()
            logger.info(f"State Observed: {state}")
            
            # decide
            action = 0
            try:
                resp = requests.post(
                    f"{rl_agent_url}/predict", 
                    json={"state": state},
                    timeout=5
                )
                if resp.status_code == 200:
                    action = resp.json().get("action", 0)
                else:
                    logger.warning(f"RL agent returns {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"Cannot reach RL agent at {rl_agent_url}: {e}")
            
            # algorithmic guardrails
            try:
                current_reps = executor.apps_v1.read_namespaced_deployment(config['deployment_name'], config['namespace']).spec.replicas
            except Exception:
                current_reps = 1
                
            if action in [0, 2] and state[3] < 0.2:
                # is memory uncontrollably leaking while cpu sits idle
                if state[4] > 0.8:
                    action = 1 # force a restart
                    logger.info("GUARDRAIL: memory leak detected. Forcing [ 1 : Restart-Pod ]")
                else:                     
                    # we artificially force the agent into No-Op if replicas are stable, or Scale-Down if confidently overprovisioned
                    if current_reps <= config.get('min_replicas', 1):
                        action = 0 # No-Op
                        # logger.info("GUARDRAIL: System perfectly idle and scaled correctly. Forcing [ 0 : No-Op ]")
                    elif current_reps > config.get('min_replicas', 1):
                        action = 3 # Scale Down
                        logger.info(f"GUARDRAIL: system idle but over-provisioned ({current_reps} pods). Forcing [ 3 : Scale-Down ]")
            
            action_names = {0: "no-op", 1: "restart-pod", 2: "scale-up", 3: "scale-down"}
            logger.info(f"Final Decision: [ {action} : {action_names.get(action, 'unknown')} ]")
            RL_ACTION_GAUGE.set(action)
            
            # execute
            if action != 0:
                result = executor.execute_action(action)
                logger.info(f"Execution Result: {result}")
            
            # orchestrate chaos (toggling)
            current_time = time.time()
            if current_time - last_chaos_time >= chaos_interval:
                # if chaos is currently active, we remove it to give the system time to idle/recover
                if RL_CHAOS_GAUGE._value.get() == 1.0:
                    chaos.remove_chaos()
                    RL_CHAOS_GAUGE.set(0)
                    logger.info("CHAOS REMOVED: System entering idle recovery phase...")
                else:
                    # if system is idle, we inject new random chaos
                    chaos_res = chaos.inject_chaos()
                    logger.warning(f"CHAOS INJECTED: {chaos_res}")
                    RL_CHAOS_GAUGE.set(1)
                    
                last_chaos_time = current_time
                
            # sleep remainder of interval
            elapsed = time.time() - loop_start
            sleep_time = max(0.1, observation_interval - elapsed)
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logger.info("Interrupt received, cleaning up active chaos experiments...")
            chaos.remove_chaos()
            break
        except Exception as e:
            logger.exception(f"Unexpected loop exception: {str(e)}")
            time.sleep(observation_interval)

if __name__ == "__main__":
    run_loop()
