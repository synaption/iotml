# iotml

**iotml** is a reference project for training machine-learning models and deploying them to edge devices managed by Kubernetes on Digital Ocean.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Documentation](#documentation)
- [Contributing](#contributing)

---

## Overview

Edge AI moves inference workloads out of centralised cloud data-centres and onto devices that are physically close to sensors, cameras, and actuators.  This reduces latency, lowers bandwidth costs, and keeps sensitive data on-premises.

**iotml** documents an end-to-end workflow:

1. **Train** a model (TensorFlow / PyTorch) on a powerful host or cloud VM.
2. **Export** the model to a portable format (TensorFlow Lite, ONNX).
3. **Package** the inference service in a Docker container.
4. **Deploy** the container to edge nodes via a Kubernetes cluster provisioned on [Digital Ocean](https://www.digitalocean.com/).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Developer Workstation / Cloud VM                            │
│                                                              │
│   Training data  ──►  Model training  ──►  Export model      │
│                             │                                │
│                    docker build & push                       │
└─────────────────────────────┼────────────────────────────────┘
                              │ (container image)
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Digital Ocean Managed Kubernetes (DOKS)                     │
│                                                              │
│   kubectl apply ──►  Deployment / DaemonSet                  │
│                             │                                │
│                    edge node pool                            │
└─────────────────────────────┼────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Edge Node(s)    │
                    │  (ARM / x86-64)   │
                    │  inference server │
                    └───────────────────┘
```

---

## Getting Started

### Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.9 | [python.org](https://www.python.org/) |
| Docker | 24 | [docs.docker.com](https://docs.docker.com/get-docker/) |
| kubectl | 1.28 | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
| doctl | 1.100 | [docs.digitalocean.com](https://docs.digitalocean.com/reference/doctl/how-to/install/) |

### Quick start

```bash
# 1. Clone this repository
git clone https://github.com/synaption/iotml.git
cd iotml

# 2. Train a sample model
python examples/train.py

# 3. Build and push the inference container
docker build -t registry.digitalocean.com/<your-registry>/iotml-inference:latest .
docker push registry.digitalocean.com/<your-registry>/iotml-inference:latest

# 4. Deploy to your Digital Ocean Kubernetes cluster
kubectl apply -f k8s/
```

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Training models](docs/training.md) | How to train, evaluate, and export ML models |
| [Kubernetes deployment](docs/kubernetes.md) | Deploying inference workloads with Kubernetes |
| [Digital Ocean setup](docs/digital-ocean.md) | Provisioning DOKS clusters and node pools |
| [Edge deployment](docs/edge-deployment.md) | End-to-end edge deployment workflow |
| [Edge-cloud planning TODO / decisions](docs/edge-cloud-vision-planning.md) | Consolidated architecture decisions, defaults, and prioritized implementation backlog |

---

## Contributing

Pull requests and issues are welcome.  Please open an issue first to discuss significant changes.

---

## License

MIT
