# llm-d Project — Issues & Solutions Log

Running log of problems hit while building the llm-d vs. plain-vLLM benchmark project, and how we solved them. Kept side-by-side with the work so the writeup/LinkedIn post can reference real debugging, not just a clean happy path.

---

## Goal

Quantify the throughput/latency benefit of llm-d (KV-cache-aware routing + disaggregated prefill/decode) vs. a plain vLLM deployment, on a small budget ($20-50), using a 2-GPU setup.

Baseline plan: RunPod GPU pod → k3s → llm-d Helm charts → benchmark vs plain vLLM.

---

## Issue 1: RunPod GPU Pods are unprivileged nested Docker containers

**What happened:** Deployed a RunPod GPU Pod (2x RTX PRO 4500, 32GB VRAM each — confirmed via `nvidia-smi`). Before installing k3s, checked whether the pod could actually run a nested Kubernetes control plane.

Diagnostics run inside the pod:
```
cat /proc/1/comm            → docker-init   (confirms this is a Docker container, not a VM)
mount | grep cgroup         → cgroup2 mounted rw with cpuset,cpu,io,memory,hugetlb,pids,rdma,misc controllers
cat /proc/self/status | grep CapEff  → 00000000a80425fb
which iptables               → (not found)
```

`00000000a80425fb` is exactly Docker's **default unprivileged** capability set — missing `CAP_SYS_ADMIN` and `CAP_NET_ADMIN`. k3s's embedded containerd needs those to create network namespaces / veth pairs for pod-to-pod networking (CNI). Without them, k3s would very likely install but fail at pod networking.

**Why it matters:** RunPod GPU Pods are containers running on RunPod's own host infra, not bare VMs — so nested container orchestration (a k8s node runs pods, which are themselves containers) hits real capability restrictions with the default pod configuration.

**Solution / decision:** Pivoted away from RunPod + self-managed k3s. Considered three options (try k3s anyway, get a privileged RunPod pod, skip k8s and run llm-d components as plain Docker containers) and instead chose a fourth: **move to a managed Kubernetes cluster (AWS EKS)** with real EC2 VMs as nodes. Managed cluster nodes are full VMs — kubelet/containerd run natively, no nested-container capability problem at all.

**Status:** RunPod pod terminated to stop billing. Moving to EKS with an L4 GPU node group (2x `g6.xlarge`, one for prefill, one for decode — also a more realistic topology since llm-d disaggregation typically separates prefill/decode across nodes anyway).

---

## Issue 2: AWS GPU quota only covers 1 node, not 2

**What happened:** Checked Service Quotas → EC2 → "Running On-Demand G and VT instances" (quota code `L-DB2E81BA`). Found an existing applied quota of **4 vCPUs**, left over from a prior request (May 10, 2026, status "Case Closed"). 4 vCPUs covers exactly one `g6.xlarge` node (4 vCPU, 1x L4 GPU) — not the two nodes needed for separate prefill/decode.

**Solution:** Filed a new quota increase request for **8 vCPUs** at account level, to cover 2x `g6.xlarge` nodes. Waiting on approval (can be instant or take a few hours).

**Status:** Pending approval.

---

## Cost tracking

| Item | Est. cost |
|---|---|
| RunPod 2x RTX PRO 4500 pod (setup + diagnosis, ~1hr) | ~$1.44 |
| EKS control plane | $0.10/hr |
| 2x g6.xlarge (1x L4 24GB each) | ~$1.61/hr combined |
| **Running EKS total estimate** | ~$1.71/hr |

Budget: $20-50 total.
