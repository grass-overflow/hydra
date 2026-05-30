import subprocess
import random
import os
import logging
from typing import Optional

logger = logging.getLogger("ChaosController")
logging.basicConfig(level=logging.INFO)

class ChaosController:
    def __init__(self, chaos_dir: str):
        self.chaos_dir = chaos_dir
        if os.path.exists(chaos_dir):
            self.experiments = [f for f in os.listdir(chaos_dir) if f.endswith('.yaml')]
        else:
            self.experiments = []
            logger.warning(f"Chaos directory {chaos_dir} not found.")
        self.active_experiment: Optional[str] = None
        
    def inject_chaos(self) -> str:
        if not self.experiments:
            logger.warning("No chaos experiments found in directory.")
            return "no chaos configs"
            
        if self.active_experiment:
            self.remove_chaos()
            
        # extract first experiment and append it to back 
        # for sequenced linear testing loop
        experiment = self.experiments.pop(0)
        self.experiments.append(experiment)
        yaml_path = os.path.join(self.chaos_dir, experiment)
        try:   
            subprocess.run(["kubectl", "apply", "-f", yaml_path], check=True, capture_output=True)
            self.active_experiment = yaml_path
            logger.info(f"Injected chaos using {experiment}")
            return f"injected {experiment}"
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to inject chaos {experiment}: {e.stderr.decode()}")
            return f"error injecting {experiment}"
        except FileNotFoundError:
            logger.error("kubectl not found. Ensure it is installed and in PATH.")
            return "kubectl not found"

    def remove_chaos(self) -> str:
        if self.active_experiment:
            try:
                subprocess.run(["kubectl", "delete", "-f", self.active_experiment], check=True, capture_output=True)
                removed_name = os.path.basename(self.active_experiment)
                self.active_experiment = None
                logger.info(f"Removed active chaos {removed_name}")
                return f"removed {removed_name}"
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to remove chaos {self.active_experiment}: {e.stderr.decode()}")
                return "error removing chaos"
            except FileNotFoundError:
                return "kubectl not found"
        return "no active chaos to remove"
