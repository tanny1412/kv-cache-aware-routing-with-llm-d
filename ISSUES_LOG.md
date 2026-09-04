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

**Solution:** Filed a new quota increase request for **12 vCPUs** at account level (extra headroom beyond the exact 8 needed for 2x `g6.xlarge`, so a rolling node replacement or minor sizing change wouldn't hit the ceiling again). Case `178783256600955`, requested 2026-08-27 08:09 ET.

**Status:** Resolved — approved same morning, ~45 min turnaround.

---

## Issue 3: EKS has no default storage class out of the box

**What happened:** While waiting on GPU quota approval, reviewed the `llm-d-deployer` quickstart installer (`llmd-installer.sh --help`) ahead of time. Its default storage class is `efs-sc`, which doesn't exist on a fresh cluster. Modern EKS also no longer ships a default EBS storage provisioner automatically — the AWS EBS CSI driver must be explicitly installed, or PVCs (model download volume, etc.) would sit stuck in `Pending`.

**Solution:** Added `iam.withOIDC: true` and an `aws-ebs-csi-driver` addon (with `wellKnownPolicies.ebsCSIController: true`) to `eks-cluster.yaml` before ever creating the cluster, so the EBS CSI driver and its IAM permissions are set up from the start. Once the cluster is up we'll create a `gp3` StorageClass and pass `--storage-class gp3` to the llm-d installer instead of the default `efs-sc`.

**Status:** Resolved preemptively (caught before hitting it).

**Verified after cluster creation:** `kubectl describe storageclass gp2` confirmed EKS does auto-create a `gp2` StorageClass (via the legacy, deprecated in-tree `kubernetes.io/aws-ebs` provisioner) — but `IsDefaultClass: No`. So the precise claim isn't "EKS has no storage class," it's "EKS ships a non-default StorageClass on a deprecated provisioner" — any PVC without an explicit `storageClassName` would still have hit `Pending` forever without our fix. Applying `k8s/storage-class.yaml` (CSI-based `gp3`, marked default) resolved this correctly.

## Open decision: gateway type for llm-d installer

The installer supports `istio`, `kgateway`, `gke-l7-rilb`, `gke-l7-regional-external-managed` via `--gateway` (default: `istio`). Since we're on EKS (not GKE), the GKE-specific options don't apply. Leaning toward `kgateway` since it's llm-d's more lightweight reference implementation, avoiding a full Istio install — final call deferred until cluster is live and we can test.

## Issue 4: `eksctl` rejected `AL2_x86_64_GPU` AMI family

**What happened:** Running `eksctl create cluster -f eks-cluster.yaml` failed immediately with:
```
Error: AMI Family AL2_x86_64_GPU is not supported - use one of: AmazonLinux2023, AmazonLinux2, UbuntuPro2404, ...
```
Amazon Linux 2 (and its GPU-specific AMI family) is being deprecated across EKS; newer eksctl versions no longer accept `AL2_x86_64_GPU` as a nodegroup AMI family.

**Solution:** Switched `amiFamily` to `AmazonLinux2023` in `eks-cluster.yaml`. AL2023 has separate "accelerated" AMI variants for NVIDIA GPUs vs. AWS Neuron, and eksctl automatically selects the correct accelerated AMI when the node group's `instanceType` is a GPU instance (like `g6.xlarge`) — no extra flag needed.

**Status:** Resolved.

## Issue 5: ASG cross-AZ rebalancing raced with transient GPU capacity shortage

**What happened:** After cluster #2 came up, `kubectl get nodes` briefly showed 3 nodes (should be 2), with the oldest one `Ready,SchedulingDisabled`. Investigated via `aws autoscaling describe-scaling-activities` on the underlying ASG:
- The node group's ASG spans multiple AZs (no explicit subnet pinning), and tries to keep instance counts balanced across AZs even after initial launch.
- It saw 2 instances in `us-east-1c`, 0 in `us-east-1f`, and repeatedly tried launching a `g6.xlarge` in `us-east-1f` to rebalance — failing ~5 times over 5 minutes with `InsufficientInstanceCapacity` (transient regional/AZ-level GPU capacity contention, not our config's fault).
- It eventually succeeded, bringing the group to 3 instances, then immediately terminated one `us-east-1c` instance to shrink back to `desiredCapacity: 2`.

**Solution:** None needed — self-resolved. `kubectl get nodes` confirmed back to exactly 2 `Ready` nodes a few minutes later.

**Status:** Resolved (transient, no action taken). Worth knowing for the writeup: GPU instance capacity can be genuinely scarce per-AZ, and a multi-AZ managed node group's self-balancing can look alarming (extra node, cordoned node) while actually being benign.

**Confirmed recurring:** Happened again on cluster recreation #3 (different AZ pair this time: `us-east-1b`/`us-east-1d`), same root cause confirmed via `describe-scaling-activities`, same self-resolution within ~1-2 minutes. This appears to be standard behavior for any multi-AZ managed node group using GPU instance types, not a one-off fluke — worth mentioning as a known "gotcha to expect" in the writeup rather than treating each recurrence as a new problem.

## Issue 6: vLLM refused to start — KV cache memory required exceeds available GPU memory

**What happened:** After both baseline pods reached `Running`, they crash-looped shortly after model load completed. `kubectl logs <pod> --previous` showed:
```
ValueError: To serve at least one request with the model's max seq len (131072), (14.0 GiB KV cache is
needed, which is larger than the available KV cache memory (12.54 GiB).
```
`Llama-3.2-3B-Instruct`'s own config declares a max context length of 131,072 tokens. By default, vLLM reserves enough GPU memory at startup to guarantee it can serve a request at that full length — which requires 14 GiB of KV cache. After model weights (6.04 GiB) and other overhead, only 12.54 GiB was free on the `g6.xlarge`'s single L4 GPU (24GB total). vLLM refuses to start rather than silently under-provision.

**Solution:** Added `--max-model-len 8192` to the container args in `k8s/baseline/deployment.yaml`. This caps the *promised* max request length far below the model's theoretical max, which our actual benchmark traffic (ShareGPT-style prompts) never approaches anyway — so nothing real is lost, and the KV cache reservation shrinks to comfortably fit available memory.

**Status:** Resolved.

## Issue 7: Deployment rollout deadlocked on exclusive GPU resources

**What happened:** After fixing Issue 6 and re-applying the updated Deployment, `kubectl get pods` showed the *old* pods still `CrashLoopBackOff` and a *new* pod stuck `Pending` indefinitely. `kubectl delete pod -l app=vllm-baseline` didn't help — the old pods just got recreated with the old (broken) config.

Root cause: Kubernetes Deployments default to `RollingUpdate`, which briefly runs old and new pods side-by-side (a "surge" pod) during a transition. That assumes there's spare capacity — false here, since both GPUs were already fully claimed by the 2 old (crash-looping, but still *existing* and still holding their GPU) pods. The new surge pod could never schedule, and the old ReplicaSet kept recreating its own pods whenever deleted, since its desired replica count was untouched.

**Solution:** Identified the two separate `ReplicaSet` objects behind the Deployment (`kubectl get replicasets -l app=vllm-baseline`) and scaled the *old* one directly to 0 (`kubectl scale replicaset <old-rs-name> --replicas=0`), which deleted its pods and stopped it from recreating them — freeing the GPUs for the new ReplicaSet. Also added `strategy: { type: Recreate }` to `deployment.yaml` so future template changes kill all old pods before creating new ones, avoiding this deadlock permanently for any workload with zero spare exclusive-resource capacity (GPUs, in our case).

**Status:** Resolved.

## Issue 8: `kubectl port-forward` bypasses Service load balancing entirely

**What happened:** Ran the custom multi-turn benchmark (`benchmark/multiturn_bench.py`) against the baseline via `kubectl port-forward svc/vllm-baseline 8000:8000`. Results showed turn 1 avg TTFT (0.202s) and turn 2+ avg TTFT (0.212s) nearly identical — which contradicted the expected behavior (turn 2+ should sit roughly halfway between a cache-hit and cache-miss latency, per the ~50% routing-odds prediction with 2 replicas and no cache awareness).

Root cause: `kubectl port-forward` to a Service does **not** load-balance across the Service's backend pods. It selects a single pod when the tunnel is established and forwards all traffic to that one pod for the entire session — it bypasses the Service/kube-proxy routing layer completely. So every one of the 54 test requests, across all 6 "concurrent" simulated conversations, actually landed on the same single pod. There was never a possible "wrong pod, cold cache" case, which is why turn 1 and turn 2+ looked the same — not because routing doesn't matter, but because our test setup made routing impossible to vary.

**Solution:** Benchmark traffic must originate from **inside** the cluster to exercise the Service's real ClusterIP/kube-proxy load balancing — run the benchmark script from a pod inside the cluster targeting `http://vllm-baseline:8000` by in-cluster DNS name, instead of using `kubectl port-forward` as the traffic path for anything measuring routing behavior. (`port-forward` is still fine for one-off manual `curl` sanity checks against a single pod, like we did earlier — just not valid for anything measuring load-balancing/routing behavior across replicas.)

**Status:** Resolved — switched to running the benchmark from an in-cluster pod (`kubectl run bench-runner --image=python:3.11-slim`, `kubectl cp` the script in, `kubectl exec` to run it against `http://vllm-baseline:8000`).

**Follow-up improvement:** initial in-cluster run used 6 short hand-written conversations (turn 1 avg 0.068s, turn 2+ avg 0.092s) — a real but modest gap, because short accumulated context makes a cache miss cheap to recompute even when it happens. Replaced hand-written prompts with 18 real conversations extracted from the actual ShareGPT dataset (`benchmark/extract_conversations.py`, selecting an even spread across the length distribution rather than the first N found) and raised generated-reply length (`max_tokens` 200 → 400) so accumulated context by turn 3-4 is substantially larger. Re-ran: **turn 1 avg TTFT 0.097s, turn 2+ avg TTFT 0.126s (n=54/123)** — a clearer ~30% gap, with individual cold-cache-miss outliers visibly spiking to 0.32-0.44s against a typical 0.08-0.15s range. This is the dataset used going forward (`benchmark/baseline_multiturn.json`).

## Cost tracking

| Item | Est. cost |
|---|---|
| RunPod 2x RTX PRO 4500 pod (setup + diagnosis, ~1hr) | ~$1.44 |
| EKS control plane | $0.10/hr |
| 2x g6.xlarge (1x L4 24GB each) | ~$1.61/hr combined |
| **Running EKS total estimate** | ~$1.72/hr |

Budget: $20-50 total.

**Actual spend so far:** Session 1 — cluster up 2026-08-27 11:59 to 13:35 (~1h36m) verifying nodes/addons ≈ **$2.75**. Deleted before stepping away to avoid idle billing.
