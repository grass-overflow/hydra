FROM python:3
RUN apt-get update
RUN apt install iputils-ping dnsutils iproute2 -y
WORKDIR /server
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py .
COPY container_metrics.py .
COPY templates ./templates/
ENTRYPOINT ["python3", "server.py"]
