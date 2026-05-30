#!/usr/bin/bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")

eval $(minikube docker-env)
docker build -t rtsm-hydra "$PROJECT_ROOT/hydra/"
docker build -t rtsm-frontend "$PROJECT_ROOT/frontend/"
docker build -t rl-controller "$PROJECT_ROOT/rl_controller/"
