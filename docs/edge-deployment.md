# End-to-End Edge Deployment Workflow

This guide ties together model training, containerisation, cluster provisioning, and deployment into a single repeatable workflow for shipping AI inference to edge nodes.

---

## Table of Contents

- [Overview](#overview)
- [Step 1 — Train and Export the Model](#step-1--train-and-export-the-model)
- [Step 2 — Build and Push the Container Image](#step-2--build-and-push-the-container-image)
- [Step 3 — Provision the Kubernetes Cluster](#step-3--provision-the-kubernetes-cluster)
- [Step 4 — Deploy to Edge Nodes](#step-4--deploy-to-edge-nodes)
- [Step 5 — Verify the Deployment](#step-5--verify-the-deployment)
- [Step 6 — Update a Model (CI/CD)](#step-6--update-a-model-cicd)
- [Troubleshooting](#troubleshooting)
- [Reference Architecture Diagram](#reference-architecture-diagram)

---

## Overview

```
Train → Export → Containerise → Push → Deploy → Verify → (loop)
```

Each step is described below.  A GitHub Actions workflow that automates steps 2–4 is provided in [Step 6](#step-6--update-a-model-cicd).

---

## Step 1 — Train and Export the Model

Follow the [Training guide](training.md) to produce a portable model file.

```bash
# Example: TFLite
python train.py --epochs 20 --output saved_model/
python export_tflite.py --input saved_model/ --output model.tflite

# Verify the exported model locally
python -c "
import tflite_runtime.interpreter as tflite
interp = tflite.Interpreter('model.tflite')
interp.allocate_tensors()
print('Input details:', interp.get_input_details())
print('Output details:', interp.get_output_details())
"
```

Commit the exported model to your model registry or object storage (e.g. Digital Ocean Spaces):

```bash
# Upload to Digital Ocean Spaces (S3-compatible)
aws s3 cp model.tflite \
  s3://<your-space>/models/v1.0.0/model.tflite \
  --endpoint-url https://nyc3.digitaloceanspaces.com
```

---

## Step 2 — Build and Push the Container Image

Build an image that embeds (or downloads at startup) the exported model.

```bash
# Set your registry and version
REGISTRY=registry.digitalocean.com/iotml-registry
VERSION=v1.0.0

# Authenticate
doctl registry login

# Build (multi-arch for ARM edge nodes if needed)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t $REGISTRY/iotml-inference:$VERSION \
  --push .
```

> **Tip:** Pin the version tag to a Git SHA (`$(git rev-parse --short HEAD)`) for traceability.

---

## Step 3 — Provision the Kubernetes Cluster

If you haven't done this yet, follow the [Digital Ocean setup guide](digital-ocean.md).

```bash
# Quick check
kubectl get nodes -o wide
# NAME               STATUS   ROLES    AGE   VERSION
# default-pool-xxx   Ready    <none>   10m   v1.30.1
# edge-pool-yyy      Ready    <none>   5m    v1.30.1
```

Confirm the edge node pool is labelled and tainted:

```bash
kubectl get nodes -l role=edge
kubectl describe node <edge-node-name> | grep -A5 Taints
```

---

## Step 4 — Deploy to Edge Nodes

Apply all manifests in one command:

```bash
kubectl apply -f k8s/
```

Or individually:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/daemonset.yaml
kubectl apply -f k8s/service.yaml
```

Wait for the DaemonSet to be fully ready:

```bash
kubectl rollout status daemonset/iotml-inference-edge
```

---

## Step 5 — Verify the Deployment

### Check pod status

```bash
kubectl get pods -l app=iotml-inference-edge -o wide
# NAME                        READY   STATUS    NODE
# iotml-inference-edge-abc12  1/1     Running   edge-pool-yyy
```

### Test the inference endpoint

Port-forward to a running pod:

```bash
kubectl port-forward pod/iotml-inference-edge-abc12 8080:8080
```

Send a test image:

```bash
curl -s -X POST http://localhost:8080/predict \
  -F "file=@test_image.jpg" | python -m json.tool
# {
#   "class_id": 0,
#   "scores": [0.982, 0.018]
# }
```

### Check logs

```bash
kubectl logs -l app=iotml-inference-edge --tail=50 --follow
```

### Check resource usage

```bash
kubectl top pods -l app=iotml-inference-edge
```

---

## Step 6 — Update a Model (CI/CD)

Below is a minimal GitHub Actions workflow that trains (or retrieves) a new model, builds a new image, and rolls it out automatically on every push to `main`.

`.github/workflows/deploy.yml`

```yaml
name: Build and Deploy Inference

on:
  push:
    branches: [main]
    paths:
      - "model/**"
      - "Dockerfile"
      - "inference_server.py"
      - "k8s/**"

env:
  REGISTRY: registry.digitalocean.com/iotml-registry
  IMAGE: iotml-inference

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install doctl
        uses: digitalocean/action-doctl@v2
        with:
          token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}

      - name: Log in to DOCR
        run: doctl registry login --expiry-seconds 600

      - name: Set image tag
        id: tag
        run: echo "TAG=${GITHUB_SHA::8}" >> $GITHUB_OUTPUT

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE }}:${{ steps.tag.outputs.TAG }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install doctl
        uses: digitalocean/action-doctl@v2
        with:
          token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}

      - name: Configure kubectl
        run: doctl kubernetes cluster kubeconfig save iotml-cluster

      - name: Set image tag
        id: tag
        run: echo "TAG=${GITHUB_SHA::8}" >> $GITHUB_OUTPUT

      - name: Update DaemonSet image
        run: |
          kubectl set image daemonset/iotml-inference-edge \
            inference=${{ env.REGISTRY }}/${{ env.IMAGE }}:${{ steps.tag.outputs.TAG }}
          kubectl rollout status daemonset/iotml-inference-edge --timeout=5m
```

Add the following secret to your GitHub repository settings:

| Secret | Value |
|--------|-------|
| `DIGITALOCEAN_ACCESS_TOKEN` | Your DO Personal Access Token |

---

## Troubleshooting

### Pod stuck in `ImagePullBackOff`

```bash
kubectl describe pod <pod-name>
# Look for: Failed to pull image ... unauthorized
```

Fix: Ensure the DOCR pull secret is created and referenced in the pod spec.  See [Connecting the Registry to the Cluster](digital-ocean.md#connecting-the-registry-to-the-cluster).

### Pod stuck in `Pending`

```bash
kubectl describe pod <pod-name>
# Look for: 0/3 nodes are available: ... node(s) had taint
```

Fix: Check node labels and tolerations match your DaemonSet/Deployment spec.

### High memory usage / OOMKilled

- Reduce batch size in the inference server.
- Use a quantized model (see [Quantization and Optimization](training.md#quantization-and-optimization)).
- Increase the pod memory limit in your manifest.

### Slow inference on ARM nodes

- Ensure the container was built for `linux/arm64` (multi-arch build).
- Use TFLite with the XNNPACK delegate or enable NEON optimizations.

---

## Reference Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│  GitHub / CI                                                      │
│  ┌──────────┐  push image   ┌──────────────────────────────────┐  │
│  │  build   │──────────────►│  Digital Ocean Container Registry│  │
│  └──────────┘               └──────────────────┬───────────────┘  │
│       │ kubectl set image                       │ pull             │
│       ▼                                         │                  │
│  ┌─────────────────────────────────────────────▼────────────────┐ │
│  │  DOKS Control Plane                                          │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │  default node pool (3 × s-4vcpu-8gb)                 │    │ │
│  │  │  (training jobs, dev workloads)                      │    │ │
│  │  └──────────────────────────────────────────────────────┘    │ │
│  │  ┌──────────────────────────────────────────────────────┐    │ │
│  │  │  edge node pool (2 × s-2vcpu-4gb, taint: edge)       │    │ │
│  │  │  ┌────────────────┐  ┌────────────────┐              │    │ │
│  │  │  │  edge-node-1   │  │  edge-node-2   │              │    │ │
│  │  │  │  inference pod │  │  inference pod │              │    │ │
│  │  │  └───────┬────────┘  └───────┬────────┘              │    │ │
│  │  └──────────┼───────────────────┼───────────────────────┘    │ │
│  └─────────────┼───────────────────┼────────────────────────────┘ │
└────────────────┼───────────────────┼───────────────────────────────┘
                 │ HTTP /predict     │ HTTP /predict
                 ▼                   ▼
            IoT sensors / cameras / local clients
```

---

## Next Steps

- Add an [Ingress controller](https://kubernetes.github.io/ingress-nginx/) to expose inference endpoints over HTTPS.
- Integrate [Prometheus + Grafana](kubernetes.md#monitoring) for inference latency dashboards.
- Explore [KServe](https://kserve.github.io/website/) for production-grade model serving on Kubernetes.
- Evaluate [K3s](https://k3s.io/) or [MicroK8s](https://microk8s.io/) for ultra-constrained edge nodes.
