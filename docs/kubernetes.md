# Kubernetes Edge Deployment

This guide explains how to package an inference service as a Docker container and deploy it to edge nodes using Kubernetes.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Containerising the Inference Server](#containerising-the-inference-server)
- [Pushing to a Container Registry](#pushing-to-a-container-registry)
- [Kubernetes Concepts for Edge Workloads](#kubernetes-concepts-for-edge-workloads)
- [Writing Kubernetes Manifests](#writing-kubernetes-manifests)
  - [Deployment](#deployment)
  - [DaemonSet (deploy to every edge node)](#daemonset-deploy-to-every-edge-node)
  - [Service](#service)
  - [ConfigMap](#configmap)
- [Rolling Out Updates](#rolling-out-updates)
- [Monitoring](#monitoring)
- [Next Steps](#next-steps)

---

## Prerequisites

- A trained and exported model (see [Training models](training.md))
- Docker installed on your build machine
- `kubectl` configured to talk to your cluster (see [Digital Ocean setup](digital-ocean.md))
- A container registry (Digital Ocean Container Registry, Docker Hub, GHCR, etc.)

---

## Containerising the Inference Server

A minimal inference server using [FastAPI](https://fastapi.tiangolo.com/) and the TFLite runtime:

**`inference_server.py`**

```python
import io
import numpy as np
import tflite_runtime.interpreter as tflite
from fastapi import FastAPI, UploadFile
from PIL import Image

app = FastAPI()
interpreter = tflite.Interpreter(model_path="/model/model.tflite")
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

@app.post("/predict")
async def predict(file: UploadFile):
    image = Image.open(io.BytesIO(await file.read())).resize((224, 224))
    input_data = np.expand_dims(np.array(image, dtype=np.float32) / 255.0, axis=0)
    interpreter.set_tensor(input_details[0]["index"], input_data)
    interpreter.invoke()
    output = interpreter.get_tensor(output_details[0]["index"])
    return {"class_id": int(np.argmax(output)), "scores": output[0].tolist()}
```

**`Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn==0.29.0 \
    tflite-runtime==2.14.0 \
    pillow==10.3.0 \
    numpy==1.26.4

COPY inference_server.py .

# The model is mounted as a volume at runtime (see ConfigMap / PVC below)
CMD ["uvicorn", "inference_server:app", "--host", "0.0.0.0", "--port", "8080"]
```

Build locally to verify:

```bash
docker build -t iotml-inference:local .
docker run --rm -p 8080:8080 \
  -v $(pwd)/model.tflite:/model/model.tflite \
  iotml-inference:local
```

---

## Pushing to a Container Registry

Using [Digital Ocean Container Registry](https://docs.digitalocean.com/products/container-registry/):

```bash
# Authenticate
doctl registry login

# Tag and push
docker tag iotml-inference:local \
  registry.digitalocean.com/<your-registry>/iotml-inference:v1.0.0

docker push registry.digitalocean.com/<your-registry>/iotml-inference:v1.0.0
```

---

## Kubernetes Concepts for Edge Workloads

| Concept | When to use |
|---------|-------------|
| **Deployment** | Run N replicas on any available node |
| **DaemonSet** | Run exactly one pod on every matching node (ideal for edge) |
| **Node labels / taints** | Target specific physical edge nodes |
| **ConfigMap / Secret** | Inject model metadata or credentials |
| **PersistentVolumeClaim** | Store larger models on local node storage |
| **Resource limits** | Protect the node OS from runaway inference workloads |

---

## Writing Kubernetes Manifests

All manifests live in the `k8s/` directory of this repo.

### Deployment

`k8s/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iotml-inference
  labels:
    app: iotml-inference
spec:
  replicas: 2
  selector:
    matchLabels:
      app: iotml-inference
  template:
    metadata:
      labels:
        app: iotml-inference
    spec:
      containers:
        - name: inference
          image: registry.digitalocean.com/<your-registry>/iotml-inference:v1.0.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          volumeMounts:
            - name: model
              mountPath: /model
      volumes:
        - name: model
          configMap:
            name: iotml-model-config
```

### DaemonSet (deploy to every edge node)

Use a DaemonSet when you want one inference pod per physical edge node:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: iotml-inference-edge
spec:
  selector:
    matchLabels:
      app: iotml-inference-edge
  template:
    metadata:
      labels:
        app: iotml-inference-edge
    spec:
      # Only schedule on nodes labelled role=edge
      nodeSelector:
        role: edge
      tolerations:
        - key: "node-role"
          operator: "Equal"
          value: "edge"
          effect: "NoSchedule"
      containers:
        - name: inference
          image: registry.digitalocean.com/<your-registry>/iotml-inference:v1.0.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          volumeMounts:
            - name: model
              mountPath: /model
              readOnly: true
      volumes:
        - name: model
          hostPath:
            path: /opt/iotml/models
            type: Directory
```

Label an edge node:

```bash
kubectl label node <node-name> role=edge
```

### Service

Expose the inference pods within the cluster (or externally via a LoadBalancer):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: iotml-inference-svc
spec:
  selector:
    app: iotml-inference
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
  type: ClusterIP   # change to LoadBalancer for external access
```

### ConfigMap

Store the model path or metadata as configuration:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: iotml-model-config
data:
  model_version: "v1.0.0"
  model_path: "/model/model.tflite"
```

---

## Rolling Out Updates

```bash
# Update the image tag to a new version
kubectl set image deployment/iotml-inference \
  inference=registry.digitalocean.com/<your-registry>/iotml-inference:v1.1.0

# Watch the rollout
kubectl rollout status deployment/iotml-inference

# Roll back if the new version is broken
kubectl rollout undo deployment/iotml-inference
```

---

## Monitoring

Install [Prometheus + Grafana](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack) via Helm:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

Expose basic metrics from the FastAPI server with the `prometheus-fastapi-instrumentator` package:

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

---

## Next Steps

- [Provision a Digital Ocean Kubernetes cluster →](digital-ocean.md)
- [End-to-end edge deployment workflow →](edge-deployment.md)
