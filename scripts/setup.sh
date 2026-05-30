#!/usr/bin/bash

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --set chaosDaemon.runtime=docker \
  --set chaosDaemon.socketPath=/var/run/docker.sock \
  --create-namespace
