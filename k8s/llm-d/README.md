# Custom llm-d overlay (2-GPU budget)

llm-d's official `pd-disaggregation` guide (in [`llm-d/llm-d`](https://github.com/llm-d/llm-d)) is sized for production clusters (8 prefill + 2 decode replicas, 24 GPUs). These files scale that down to fit exactly 2 GPUs — 1 prefill + 1 decode, TP=1, `meta-llama/Llama-3.2-3B-Instruct` — matching this project's `g6.xlarge` node group. See Issue 10 in [`../../ISSUES_LOG.md`](../../ISSUES_LOG.md) for why this was needed.

**Not self-contained** — these reference the shared recipes inside `llm-d/llm-d`'s own directory tree via relative paths, the same way the project's own `coreweave`/`aws` overlays do. To use them:

1. Clone `https://github.com/llm-d/llm-d.git`.
2. Copy `modelserver-mini-overlay/` to `llm-d/guides/pd-disaggregation/modelserver/gpu/vllm/mini/` in that clone.
3. Copy `router-mini-values/mini.values.yaml` to `llm-d/guides/pd-disaggregation/router/mini.values.yaml` in that clone.
4. Follow `llm-d/guides/pd-disaggregation/README.md`'s install steps, substituting the `mini` overlay for `INFRA_PROVIDER` and adding `-f .../router/mini.values.yaml` to the `helm install` command.

## What each file changes vs. the base recipe

- `modelserver-mini-overlay/kustomization.yaml` — uses the plain `gpu-vllm/release` and `routing-sidecar/release` image components (public, version-pinned) instead of hardware-specific ones (EFA/RDMA), which don't apply to plain `g6.xlarge`.
- `modelserver-mini-overlay/patch-prefill.yaml`, `patch-decode.yaml` — `replicas: 1`, `--tensor-parallel-size=1`, `nvidia.com/gpu: 1`, our model, and reduced CPU/memory (1500m/6Gi) to fit a `g6.xlarge`'s ~3.92 vCPU/14GB allocatable.
- `router-mini-values/mini.values.yaml` — shrinks the router's default EPP + Envoy sidecar resource requests (8 CPU/16Gi combined by default — bigger than an entire node) down to 500m CPU/1Gi combined.
