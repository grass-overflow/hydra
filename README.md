# Project hydra

## Starting the cluster
- Make sure minikube is up and running
  ```minikube start```
- Run the build script to build required images
  ```chmod +x build.sh && ./build.sh```
- Run the setup script to add chaosmesh to the kubernetes cluster
  ```chmod +x setup.sh && ./setup.sh```
- Run the start script to apply the config files 
  ```chmod +x start.sh && ./start.sh```
- ```start.sh``` starts a tunnel that exposes all services. This needs to be running in the background
- In another terminal, get the external IP address of the ingress controller
  ```kubectl get svc -n ingress-nginx```
- Copy the external IP shown and add an entry in your ```/etc/hosts``` file on the host machine
  ```<External IP>    rtsm.com```
- ```http://rtsm.com``` should now take you to the dashboard

## Components:
  1. A stock monitoring dashboard built with React
  2. Hydra backend that fetches live stock data using the Yahoo Finance API while monitoring system metrics
  3. Monitoring stack comprising of Prometheus and Grafana to periodically scrape metrics data and visualize it

## Project Structure:

### Repo
The repo is divided into multiple directories:
- ```chaosmesh/``` - YAML files for various chaos experiments
- ```frontend/``` - Stock monitoring dashboard
- ```hydra/``` - Backend server for fetching live stock data
- ```kb8-configs/``` - Various config files for the kubernetes cluster
- ```scripts/``` - Scripts to build, setup, and start the kb8 cluster

### Cluster Design:
- There are 4 deployments:
    1. Frontend Dashboard
    2. Hydra backend server
    3. Prometheus
    4. Grafana

- Kubernetes Ingress-Nginx is used to route to these endpoints:
    - ```/``` - Stock Monitoring Dashboard
    - ```/data``` - Hydra server for fetching live stock data
    - ```/metrics``` - System Metrics in prometheus format
    - ```/health``` - Returns ```true``` if the Yahoo Finance API is reachable. Used for probing for liveness and readiness
    - ```/dashboard``` - Grafana dashboard for monitoring metrics

- Kubernetes native tool ```kustomize``` is used to automatically apply the configuration files and setup config maps

- Prometheus automatically finds the correct ```/metrics``` endpoint to scrape using the ```rbac.yaml``` and Kubernetes Service Discovery

- Grafana has a persistent volume claim to store its data

