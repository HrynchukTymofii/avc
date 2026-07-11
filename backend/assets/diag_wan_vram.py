"""One-off diagnostic: attribute GPU memory after loading Wan2.2 the same way
wan_pipeline.load()/to_gpu() does. Placed in assets/ (a mounted volume) so it
can run without an image rebuild:

    docker compose restart backend   # free the CPU-resident copy first
    docker compose exec backend python /app/assets/diag_wan_vram.py
"""

import gc

import torch

GB = 1024**3
CKPT = "/app/models/wan2.2-ti2v-5b"
COMPONENTS = ("transformer", "text_encoder", "vae")


def param_gb(module: torch.nn.Module) -> float:
    return sum(t.numel() * t.element_size() for t in module.state_dict().values()) / GB


def cuda_param_gb(module: torch.nn.Module) -> float:
    return (
        sum(t.numel() * t.element_size() for t in module.state_dict().values() if t.is_cuda) / GB
    )


def main() -> None:
    import diffusers
    import transformers
    from diffusers import WanImageToVideoPipeline, WanPipeline

    print(f"diffusers={diffusers.__version__} transformers={transformers.__version__}")
    print(f"torch={torch.__version__} cuda_available={torch.cuda.is_available()}")

    pipe = WanPipeline.from_pretrained(CKPT, torch_dtype=torch.bfloat16)
    for name in COMPONENTS:
        module = getattr(pipe, name)
        loaded_dtype = next(module.parameters()).dtype
        if loaded_dtype != torch.bfloat16:
            module.to(dtype=torch.bfloat16)
        print(f"{name}: {param_gb(module):.2f} GB on CPU (loaded as {loaded_dtype})")
    print(f"transformer_2: {pipe.transformer_2}")
    print(f"transformer params: {sum(p.numel() for p in pipe.transformer.parameters()) / 1e9:.2f}B")
    print(f"text_encoder params: {sum(p.numel() for p in pipe.text_encoder.parameters()) / 1e9:.2f}B")

    i2v = WanImageToVideoPipeline.from_pipe(pipe)
    for name in COMPONENTS:
        print(f"i2v shares {name}: {getattr(i2v, name) is getattr(pipe, name)}")

    pipe.to("cuda")
    free, total = torch.cuda.mem_get_info()
    print(
        f"after to(cuda): free={free / GB:.2f} GB of {total / GB:.2f} GB, "
        f"torch_allocated={torch.cuda.memory_allocated() / GB:.2f} GB"
    )
    for name in COMPONENTS:
        print(f"{name} weights on GPU: {cuda_param_gb(getattr(pipe, name)):.2f} GB")
    for name in COMPONENTS:
        print(f"i2v {name} weights on GPU: {cuda_param_gb(getattr(i2v, name)):.2f} GB")

    # Anything the per-module sums miss shows up here with shape and dtype.
    buckets: dict[tuple[str, tuple], int] = {}
    for obj in gc.get_objects():
        try:
            if torch.is_tensor(obj) and obj.is_cuda:
                key = (str(obj.dtype), tuple(obj.shape))
                buckets[key] = buckets.get(key, 0) + obj.numel() * obj.element_size()
        except Exception:
            continue
    print("largest CUDA tensor groups:")
    for (dtype, shape), size in sorted(buckets.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {size / GB:6.2f} GB  {dtype}  {shape}")


if __name__ == "__main__":
    main()
