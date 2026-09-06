# KV-Cache-Aware Routing with llm-d

A hands-on benchmark project comparing [llm-d](https://llm-d.ai) (a Kubernetes-native distributed inference stack built on vLLM) against a plain vLLM deployment, to quantify what KV-cache-aware routing and disaggregated prefill/decode actually buy you in throughput and latency.

## Why this project

Serving LLMs behind a naive load balancer has two blind spots:
- **Prefill and decode compete for the same GPU.** Prefill (processing the prompt) is compute-bound; decode (generating tokens) is memory-bandwidth-bound. A long incoming prompt can stall token generation for requests already in flight.
- **Generic load balancers are blind to KV cache.** A follow-up request in the same conversation might get routed to a cold replica instead of the one that already has that conversation's KV cache resident in GPU memory.

llm-d addresses both with a smart Inference Gateway (EndpointPicker) and disaggregated prefill/decode worker pools. This project deploys both a baseline (plain vLLM, round-robin) and an llm-d setup on identical hardware, and benchmarks them under the same workload to get real numbers instead of taking the benefit on faith.

## Architecture

**Baseline:** 2 identical vLLM replicas behind a standard Kubernetes Service (round-robin load balancing), serving `meta-llama/Llama-3.2-3B-Instruct`.

**llm-d:** Same 2 GPUs, reconfigured as 1 dedicated prefill worker + 1 dedicated decode worker, registered in a single `InferencePool` behind llm-d's Router (Envoy sidecar + EndpointPicker, "Standalone Mode"). The EndpointPicker (EPP) routes each request based on real-time KV-cache/load signals rather than round-robin, and orchestrates the prefill → KV-cache-transfer → decode handoff via NIXL. Deployed from `llm-d/llm-d`'s `guides/pd-disaggregation` recipe, scaled down to fit a 2-GPU budget (`docker.io/vllm/vllm-openai:v0.26.0` for both roles, `llm-d-router-disagg-sidecar:v0.10.0`, `llm-d-router-endpoint-picker`) — see the custom `mini` overlay under that guide's `modelserver/gpu/vllm/` directory.

> **Note on networking:** `g6.xlarge` nodes don't support RDMA-capable networking (e.g. AWS EFA), so NIXL falls back to its TCP transport for cross-node KV cache transfer instead of RDMA/InfiniBand. This means the absolute numbers here understate llm-d's best-case performance on production RDMA hardware — but the head-to-head comparison against the baseline is still valid, since it isolates the same variable (smart routing + disaggregation vs. none) under an equivalent network ceiling.

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

Both deployments are load-tested with identical traffic (`vllm`'s `benchmark_serving.py` against a ShareGPT-style mixed workload of short and long prompts, including simulated multi-turn conversations), swept across multiple concurrency levels (1, 4, 8, 16, 32, 64 concurrent requests) rather than a single load point — the goal is to see *where* and *how much* the two deployments diverge as contention increases, not just how each performs at one arbitrary load level. Compared on:
- Time-to-first-token (TTFT), P50/P90, plotted against concurrency
- Inter-token latency (ITL)
- Overall throughput (tokens/sec)

## Status

- [x] Architecture research and benchmark design
- [x] Provisioned GPU compute, hit and resolved infra blockers (see [`ISSUES_LOG.md`](./ISSUES_LOG.md))
- [x] EKS cluster with GPU node group live
- [x] Baseline vLLM deployment live and validated (2 replicas, 1 GPU each, confirmed serving real completions)
- [x] Benchmark #1 complete: baseline multi-turn cache-routing test and load-curve test across concurrency 1-64, both using real ShareGPT conversations/prompts
- [x] llm-d deployed and validated end-to-end (real prefill/decode disaggregation + EPP router, confirmed serving real completions) — `llm-d-deployer` turned out to be abandoned upstream; switched to the current `llm-d/llm-d` "Standalone Mode" path and hand-wrote a scaled-down overlay to fit our 2-GPU budget (see Issues 9-10 in `ISSUES_LOG.md`)
- [x] Benchmark #2 complete: both benchmark scripts re-run against llm-d for direct comparison
- [x] Results writeup and comparison — see below

See [`ISSUES_LOG.md`](./ISSUES_LOG.md) for a real-time log of problems hit along the way (e.g. RunPod's nested-container GPU pods not being privileged enough to run k3s) and how they were resolved — infra debugging is half the point of this project.

## Results

**Baseline concurrency/latency curve** (plain vLLM, 2 replicas, round-robin — no cache-aware routing, no disaggregation):

![Baseline load curve: TTFT and throughput vs. concurrency](./benchmark/baseline_load_curve.png)

TTFT holds under 75ms through concurrency 16, then climbs sharply — P90 reaches 219ms at concurrency 64, a ~4.8x increase over the single-request baseline — while throughput keeps scaling close to linearly. That gap between "throughput is fine" and "latency is degrading" is exactly the contention llm-d's disaggregated prefill/decode is meant to relieve.

**Baseline multi-turn cache-routing test** (same deployment — round-robin has no memory of which pod handled a conversation's earlier turns):

![Baseline multi-turn TTFT: turn 1 vs turn 2+ distribution](./benchmark/baseline_multiturn.png)

Turn 1 (n=54, no prior cache to hit or miss) stays tightly bounded between 48-155ms. Turn 2+ (n=123) has a long right tail — a minority of requests spike to 250-444ms — consistent with round-robin occasionally routing a follow-up to a cold replica, though less evenly split than a pure 50/50 coin flip would predict (mean 126ms vs. median 93ms — the average is pulled up by a smaller tail of slow outliers, not an even bimodal split).

### llm-d vs. baseline — the actual comparison

![Baseline vs llm-d: TTFT and throughput vs. concurrency](./benchmark/comparison_load_curve.png)

![Baseline vs llm-d: multi-turn TTFT](./benchmark/comparison_multiturn.png)

**The headline result is not what the "smart routing helps" story predicts: in this setup, llm-d is slower and lower-throughput than the plain baseline at every concurrency level, and slower on both turn 1 and turn 2+ in the multi-turn test.** That's a real, honestly-measured result, and it's worth explaining precisely rather than either overclaiming a win or dismissing it as a bug — it isn't one.

**Why:** disaggregation isn't free. Every single request in the P/D setup — including turn 1, which has no cache to route around at all — pays for an extra network hop and a cross-pod NIXL KV-cache transfer that the baseline's single-hop architecture simply doesn't have (baseline does prefill and decode in the same process). Recall the earlier networking caveat: `g6.xlarge` nodes have no RDMA-capable interconnect (no AWS EFA), so NIXL falls back to its TCP transport — which NIXL's own docs describe as "extremely slow... targeted for local development," not the fast path the architecture is designed around. For a small 3B model with short-to-medium prompts, that per-request tax outweighs any benefit disaggregation could provide, on this hardware.

**The mechanism still shows through, just not enough to win overall:** within llm-d's own numbers, turn 2+ (mean 521ms) is a real ~58% faster than turn 1 (mean 1247ms) — evidence that session/cache-aware routing is doing *something* directionally correct — it just isn't enough to close a >10x architectural gap opened by TCP-bound NIXL transfer on hardware this small.

**This actually matches llm-d's own documented guidance**, which we found while building the deployment: the `pd-disaggregation` guide explicitly recommends disaggregation for *"medium-large models... longer input sequence lengths (e.g. 10k ISL | 1k OSL, not 200 ISL | 200 OSL)"* — almost a direct description of what our setup is *not*. Our workload (a 3B model, short prompts, no RDMA) sits squarely in the regime llm-d's own maintainers say disaggregation isn't targeted at. The honest conclusion isn't "llm-d doesn't work" — it's "disaggregation is a real engineering tradeoff with a workload- and hardware-dependent break-even point, and this project measured which side of that line a small-model / no-RDMA / short-prompt deployment falls on."

## Acknowledgments

Built on [llm-d](https://llm-d.ai) and [vLLM](https://github.com/vllm-project/vllm).
