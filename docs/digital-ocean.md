# Digital Ocean Setup

This guide walks through provisioning a [Digital Ocean Managed Kubernetes (DOKS)](https://docs.digitalocean.com/products/kubernetes/) cluster, a container registry, and an edge node pool for iotml workloads.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installing doctl](#installing-doctl)
- [Creating a Container Registry](#creating-a-container-registry)
- [Provisioning a DOKS Cluster](#provisioning-a-doks-cluster)
  - [Choosing a Region](#choosing-a-region)
  - [Choosing Node Sizes](#choosing-node-sizes)
  - [Creating the Cluster with doctl](#creating-the-cluster-with-doctl)
  - [Creating the Cluster with Terraform](#creating-the-cluster-with-terraform)
- [Configuring kubectl](#configuring-kubectl)
- [Adding an Edge Node Pool](#adding-an-edge-node-pool)
- [Connecting the Registry to the Cluster](#connecting-the-registry-to-the-cluster)
- [Upgrading and Scaling](#upgrading-and-scaling)
- [Cost Considerations](#cost-considerations)
- [Next Steps](#next-steps)

---

## Prerequisites

- A [Digital Ocean](https://cloud.digitalocean.com/) account
- A [Personal Access Token](https://cloud.digitalocean.com/account/api/tokens) with **read** and **write** scopes
- `doctl` CLI (see below)
- `kubectl` ≥ 1.28
- (Optional) Terraform ≥ 1.5 for infrastructure-as-code

---

## Installing doctl

```bash
# macOS
brew install doctl

# Linux (amd64)
curl -sL https://github.com/digitalocean/doctl/releases/download/v1.100.0/doctl-1.100.0-linux-amd64.tar.gz \
  | tar xzv
sudo mv doctl /usr/local/bin/

# Authenticate
doctl auth init        # paste your Personal Access Token when prompted
doctl account get      # verify it works
```

---

## Creating a Container Registry

Digital Ocean Container Registry (DOCR) stores the Docker images you deploy to your cluster.

```bash
# Create a registry (starter tier is free, basic/professional support more repos)
doctl registry create iotml-registry --region nyc3 --subscription-tier starter

# Log Docker in to the registry
doctl registry login

# View your registry endpoint
doctl registry get
# → registry.digitalocean.com/iotml-registry
```

---

## Provisioning a DOKS Cluster

### Choosing a Region

Pick the Digital Ocean region closest to your edge deployment site to minimise latency between the control plane and nodes.

```bash
doctl kubernetes options regions
```

Common choices: `nyc3` (New York), `sfo3` (San Francisco), `fra1` (Frankfurt), `sgp1` (Singapore).

### Choosing Node Sizes

| Node slug | vCPU | RAM | Monthly cost | Use |
|-----------|------|-----|-------------|-----|
| `s-2vcpu-4gb` | 2 | 4 GB | ~$24 | Light workloads |
| `s-4vcpu-8gb` | 4 | 8 GB | ~$48 | Standard |
| `s-8vcpu-16gb` | 8 | 16 GB | ~$96 | Training / heavy inference |
| `c-4` | 4 | 8 GB | ~$72 | CPU-optimised |
| `g-4vcpu-16gb` | 4 | 16 GB | ~$126 | GPU-ready (requires GPU droplet) |

```bash
# List all available node sizes
doctl kubernetes options sizes
```

### Creating the Cluster with doctl

```bash
doctl kubernetes cluster create iotml-cluster \
  --region nyc3 \
  --version latest \
  --node-pool "name=default-pool;size=s-4vcpu-8gb;count=3;auto-scale=true;min-nodes=2;max-nodes=5" \
  --wait
```

The `--wait` flag blocks until the cluster is fully ready (usually 3–5 minutes).

### Creating the Cluster with Terraform

`infra/main.tf`

```hcl
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

variable "do_token" {}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_kubernetes_cluster" "iotml" {
  name    = "iotml-cluster"
  region  = "nyc3"
  version = "1.30.1-do.0"   # run `doctl kubernetes options versions` for latest

  node_pool {
    name       = "default-pool"
    size       = "s-4vcpu-8gb"
    node_count = 3

    auto_scale = true
    min_nodes  = 2
    max_nodes  = 5
  }
}

output "cluster_id" {
  value = digitalocean_kubernetes_cluster.iotml.id
}
```

```bash
cd infra
terraform init
terraform plan -var="do_token=$DIGITALOCEAN_TOKEN"
terraform apply -var="do_token=$DIGITALOCEAN_TOKEN"
```

---

## Configuring kubectl

```bash
# Save the kubeconfig for your new cluster
doctl kubernetes cluster kubeconfig save iotml-cluster

# Verify
kubectl get nodes
```

---

## Adding an Edge Node Pool

Add a dedicated pool for edge workloads.  Taint it so only iotml pods land there.

```bash
doctl kubernetes cluster node-pool create iotml-cluster \
  --name edge-pool \
  --size s-2vcpu-4gb \
  --count 2 \
  --tag edge \
  --taint "node-role=edge:NoSchedule"
```

Label the nodes after they join:

```bash
# List nodes
kubectl get nodes -l doks.digitalocean.com/node-pool=edge-pool

# Label each edge node
kubectl label node <node-name> role=edge
```

Your DaemonSet or Deployment can then use `nodeSelector: { role: edge }` to target this pool (see [Kubernetes deployment guide](kubernetes.md)).

---

## Connecting the Registry to the Cluster

Grant the cluster permission to pull images from your DOCR:

```bash
doctl registry kubernetes-manifest | kubectl apply -f -
```

This creates a Kubernetes Secret in the `default` namespace.  For other namespaces:

```bash
kubectl create secret docker-registry docr-secret \
  --docker-server=registry.digitalocean.com \
  --docker-username=$(doctl auth whoami) \
  --docker-password=$(doctl auth token) \
  --namespace <your-namespace>
```

Reference the secret in your pod spec:

```yaml
spec:
  imagePullSecrets:
    - name: docr-secret
```

---

## Upgrading and Scaling

```bash
# Upgrade the control plane to a new Kubernetes minor version
doctl kubernetes cluster upgrade iotml-cluster --version 1.31.0-do.0

# Scale a node pool
doctl kubernetes cluster node-pool update iotml-cluster default-pool \
  --count 5
```

---

## Cost Considerations

| Resource | Approximate monthly cost |
|----------|--------------------------|
| DOKS control plane | Free |
| 3 × `s-4vcpu-8gb` nodes | ~$144 |
| Container Registry (starter) | Free |
| Load Balancer (if needed) | ~$12 |
| Block storage (if needed) | ~$10 / 100 GB |

Use [Digital Ocean's pricing calculator](https://www.digitalocean.com/pricing) for exact estimates.  Enable cluster auto-scaling and set appropriate `minNodes` to avoid paying for idle capacity.

---

## Next Steps

- [Deploy your inference container with Kubernetes →](kubernetes.md)
- [End-to-end edge deployment workflow →](edge-deployment.md)
