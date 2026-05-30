#!/usr/bin/env bash
# ==============================================================================
# PROJECT HYDRA: OPERATIONAL TOGGLE & TEST CONTROL CENTER
# ==============================================================================
# Allows real-time toggling of control planes (Native HPA vs. PPO RL Agent)
# and manual execution of load generators and Chaos Mesh fault injectors.
# ==============================================================================

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
HPA_PATH="$PROJECT_ROOT/kb8-configs/hpa.yaml"
CHAOS_PATH="$PROJECT_ROOT/chaosmesh/cpu-stress.yaml"
NAMESPACE="hydra"

LOAD_PID_FILE="/tmp/hydra_load_gen.pid"

function print_usage() {
    echo "================================================================================"
    echo "               PROJECT HYDRA: OPERATIONAL TOGGLE CONTROL CENTER"
    echo "================================================================================"
    echo "Usage: $0 [command]"
    echo ""
    echo "Available Commands:"
    echo "  hpa        - Switch cluster to NATIVE KUBERNETES HPA control mode."
    echo "  rl         - Switch cluster to HYDRA PPO REINFORCEMENT LEARNING control mode."
    echo "  load-on    - Start background load generator (20 RPS to rtsm.com)."
    echo "  load-off   - Stop background load generator."
    echo "  chaos-on   - Manually inject Chaos Mesh CPU Stress fault."
    echo "  chaos-off  - Clean up and remove Chaos Mesh CPU Stress fault."
    echo "  status     - Show current active control mode, load status, and replicas."
    echo "================================================================================"
}

function check_k8s() {
    if ! kubectl get nodes &> /dev/null; then
        echo "[X] Error: Cannot reach Kubernetes API. Is Minikube running?"
        exit 1
    fi
}

function show_status() {
    check_k8s
    echo "--- CLUSTER CONTROL STATUS ---"
    
    # 1. Check if RL Agent is active
    RL_REPLICAS=$(kubectl get deployment chaos-rl-controller -n $NAMESPACE -o jsonpath='{.spec.replicas}' 2>/dev/null)
    HPA_ACTIVE=$(kubectl get hpa -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    
    if [ "$RL_REPLICAS" == "1" ]; then
        echo -e "  Active Control Mode : \033[0;32mHYDRA RL AGENT ACTIVE\033[0m"
    elif [ -n "$HPA_ACTIVE" ]; then
        echo -e "  Active Control Mode : \033[0;34mNATIVE KUBERNETES HPA ACTIVE\033[0m"
    else
        echo -e "  Active Control Mode : \033[0;33mNO ACTIVE CONTROLLER (Manual Scaling)\033[0m"
    fi
    
    # 2. Check replicas
    READY=$(kubectl get deployment hydra-deployment -n $NAMESPACE -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
    TOTAL=$(kubectl get deployment hydra-deployment -n $NAMESPACE -o jsonpath='{.spec.replicas}' 2>/dev/null)
    echo "  Active Replicas     : $READY/$TOTAL Pods"
    
    # 3. Check Load Generator
    if [ -f "$LOAD_PID_FILE" ] && kill -0 $(cat "$LOAD_PID_FILE") 2>/dev/null; then
        echo -e "  Load Generator      : \033[0;32mRUNNING\033[0m (PID: $(cat "$LOAD_PID_FILE"))"
    else
        echo "  Load Generator      : STOPPED"
    fi
    
    # 4. Check Chaos Mesh
    CHAOS_RUNNING=$(kubectl get stresschaos -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    if [ -n "$CHAOS_RUNNING" ]; then
        echo -e "  Chaos Mesh Status   : \033[0;31mACTIVE CHAOS INJECTED\033[0m"
    else
        echo "  Chaos Mesh Status   : CLEAN (No active faults)"
    fi
    echo "------------------------------"
}

# ==============================================================================
# COMMAND DISPATCHER
# ==============================================================================
case "$1" in
    hpa)
        check_k8s
        echo "[!] Switching to Native Kubernetes HPA Mode..."
        # Scale down RL Controller
        kubectl scale deployment chaos-rl-controller --replicas=0 -n $NAMESPACE
        # Apply standard HPA yaml
        if [ -f "$HPA_PATH" ]; then
            kubectl apply -f "$HPA_PATH" -n $NAMESPACE
            echo "[✓] Native HorizontalPodAutoscaler applied successfully."
        else
            echo "[X] Error: Could not locate hpa.yaml at $HPA_PATH"
        fi
        show_status
        ;;
        
    rl)
        check_k8s
        echo "[!] Switching to Hydra Reinforcement Learning Mode..."
        # Delete any active HPAs
        kubectl delete hpa --all -n $NAMESPACE &>/dev/null
        # Scale up RL components
        kubectl scale deployment rl-agent-service --replicas=1 -n $NAMESPACE
        kubectl scale deployment chaos-rl-controller --replicas=1 -n $NAMESPACE
        echo "[✓] Trained PPO Controller and Actor-Critic service activated."
        show_status
        ;;
        
    load-on)
        if [ -f "$LOAD_PID_FILE" ] && kill -0 $(cat "$LOAD_PID_FILE") 2>/dev/null; then
            echo "[!] Load generator is already running."
            exit 0
        fi
        
        # Test connection
        INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
        if [ -z "$INGRESS_IP" ]; then
            INGRESS_IP="rtsm.com"
        fi
        
        echo "[!] Starting load generation (20 RPS to http://$INGRESS_IP/data)..."
        
        # Simple background python load generator loop
        python3 -c "
import urllib.request, time, threading
def fetch():
    while True:
        try:
            req = urllib.request.Request('http://$INGRESS_IP/data?ticker=GOOGL', headers={'Host': 'rtsm.com'})
            urllib.request.urlopen(req, timeout=2).read()
        except:
            pass
        time.sleep(0.05)
for i in range(4):
    t = threading.Thread(target=fetch)
    t.daemon = True
    t.start()
while True:
    time.sleep(1)
" &> /dev/null &
        
        echo $! > "$LOAD_PID_FILE"
        echo "[✓] Background load generator started (PID: $!)."
        ;;
        
    load-off)
        if [ -f "$LOAD_PID_FILE" ]; then
            PID=$(cat "$LOAD_PID_FILE")
            echo "[!] Stopping load generator PID: $PID..."
            kill $PID 2>/dev/null
            rm -f "$LOAD_PID_FILE"
            echo "[✓] Load generator stopped."
        else
            echo "[!] No active load generator detected."
        fi
        ;;
        
    chaos-on)
        check_k8s
        if [ -f "$CHAOS_PATH" ]; then
            echo "[!] Injecting Chaos Mesh fault ($CHAOS_PATH)..."
            kubectl apply -f "$CHAOS_PATH" -n $NAMESPACE
            echo "[✓] Fault injected successfully. Watch the Grafana metrics spike!"
        else
            echo "[X] Error: Could not locate cpu-stress.yaml at $CHAOS_PATH"
        fi
        ;;
        
    chaos-off)
        check_k8s
        if [ -f "$CHAOS_PATH" ]; then
            echo "[!] Cleaning up Chaos Mesh faults..."
            kubectl delete -f "$CHAOS_PATH" -n $NAMESPACE &>/dev/null
            echo "[✓] Faults removed. System recovering to baseline."
        else
            echo "[X] Error: Could not locate cpu-stress.yaml at $CHAOS_PATH"
        fi
        ;;
        
    status)
        show_status
        ;;
        
    *)
        print_usage
        ;;
esac
exit 0
