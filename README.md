# KV-Cache-Aware Routing with llm-d

A hands-on benchmark project comparing [llm-d](https://llm-d.ai) (a Kubernetes-native distributed inference stack built on vLLM) against a plain vLLM deployment, to quantify what KV-cache-aware routing and disaggregated prefill/decode actually buy you in throughput and latency.

## Why this project

Serving LLMs behind a naive load balancer has two blind spots:
- **Prefill and decode compete for the same GPU.** Prefill (processing the prompt) is compute-bound; decode (generating tokens) is memory-bandwidth-bound. A long incoming prompt can stall token generation for requests already in flight.
- **Generic load balancers are blind to KV cache.** A follow-up request in the same conversation might get routed to a cold replica instead of the one that already has that conversation's KV cache resident in GPU memory.

llm-d addresses both with a smart Inference Gateway (EndpointPicker) and disaggregated prefill/decode worker pools. This project deploys both a baseline (plain vLLM, round-robin) and an llm-d setup on identical hardware, and benchmarks them under the same workload to get real numbers instead of taking the benefit on faith.

## Architecture

**Baseline:** 2 identical vLLM replicas behind a standard Kubernetes Service (round-robin load balancing), serving `meta-llama/Llama-3.2-3B-Instruct`.

**llm-d:** Same 2 GPUs, reconfigured as 1 dedicated prefill worker + 1 dedicated decode worker, registered in a single `InferencePool` behind llm-d's Inference Gateway. The EndpointPicker (EPP) routes each request based on real-time KV-cache/GPU utilization signals rather than round-robin, and orchestrates the prefill → KV-cache-transfer → decode handoff via NIXL.

## Infrastructure

- **Cluster:** AWS EKS with a managed GPU node group — 2x `g6.xlarge` (1x NVIDIA L4, 24GB VRAM each), one node per role (prefill / decode).
- **Model:** `meta-llama/Llama-3.2-3B-Instruct`
- **Serving engine:** vLLM
- **Orchestration:** Kubernetes (EKS) + llm-d Helm charts (`llm-d-deployer`) + Gateway API Inference Extension

### Estimated cost

| Item | Rate |
|---|---|
| EKS control plane | $0.10/hr |
| 2x `g6.xlarge` (1x NVIDIA L4 each) | $0.8048/hr each (~$1.61/hr combined) |
| **Total while cluster is running** | **≈ $1.72/hr** |

Cluster is torn down (`eksctl delete cluster`) as soon as both benchmark runs are complete — billing runs whether or not anything is deployed on the nodes.

## Benchmark methodology

Both deployments are load-tested with identical traffic (`vllm`'s `benchmark_serving.py` against a ShareGPT-style mixed workload of short and long prompts, including simulated multi-turn conversations) and compared on:
- Time-to-first-token (TTFT), P50/P90
- Inter-token latency (ITL)
- Overall throughput (tokens/sec)

## Status

- [x] Architecture research and benchmark design
- [x] Provisioned GPU compute, hit and resolved infra blockers (see [`ISSUES_LOG.md`](./ISSUES_LOG.md))
- [x] AWS GPU quota approved, EKS cluster config (`eks-cluster.yaml`) ready to launch
- [ ] EKS cluster with GPU node group live
- [ ] Baseline vLLM deployment + benchmark run
- [ ] llm-d deployment + benchmark run
- [ ] Results writeup and comparison

See [`ISSUES_LOG.md`](./ISSUES_LOG.md) for a real-time log of problems hit along the way (e.g. RunPod's nested-container GPU pods not being privileged enough to run k3s) and how they were resolved — infra debugging is half the point of this project.

## Results

_TBD — will be filled in once both benchmark runs are complete._

## Acknowledgments

Built on [llm-d](https://llm-d.ai) and [vLLM](https://github.com/vllm-project/vllm).
