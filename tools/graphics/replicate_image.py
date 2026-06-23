"""Image generation via Replicate — provider-generic, model as a parameter.

Replicate is a model marketplace, not a single model. This tool is therefore
**provider-scoped, not model-scoped**: the ``model`` input is any Replicate model
slug (``owner/name`` or ``owner/name:version``), so one tool + one
``REPLICATE_API_TOKEN`` unlocks the whole image catalog — FLUX, SDXL, Ideogram,
Recraft, Imagen, Qwen-Image, and more.

This mirrors the existing Replicate video tool (``tools/video/seedance_replicate.py``):
same env var, same ``/v1/models/{slug}/predictions`` endpoint, same ``Prefer: wait``
+ poll-fallback pattern.

Model-specific inputs (e.g. ``width``/``height`` for SDXL, ``style`` for Recraft)
that aren't first-class fields here can be passed through ``extra_input``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

# Best-effort per-image cost (USD) for common official models; falls back to a
# conservative default. Replicate prices official image models per output.
_MODEL_COST = {
    "black-forest-labs/flux-schnell": 0.003,
    "black-forest-labs/flux-dev": 0.025,
    "black-forest-labs/flux-1.1-pro": 0.04,
    "black-forest-labs/flux-1.1-pro-ultra": 0.06,
    "ideogram-ai/ideogram-v3-turbo": 0.03,
    "ideogram-ai/ideogram-v3-quality": 0.09,
    "recraft-ai/recraft-v3": 0.04,
    "stability-ai/sdxl": 0.01,
    "google/imagen-4": 0.04,
}
_DEFAULT_MODEL = "black-forest-labs/flux-dev"
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}


class ReplicateImage(BaseTool):
    name = "replicate_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "replicate"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.API

    dependencies = []  # checked dynamically via env var
    install_instructions = (
        "Set REPLICATE_API_TOKEN to your Replicate API token.\n"
        "  Get one at https://replicate.com/account/api-tokens"
    )
    agent_skills = ["flux-best-practices", "bfl-api"]

    capabilities = ["generate_image", "generate_illustration", "text_to_image"]
    supports = {
        "negative_prompt": True,
        "seed": True,
        "custom_size": True,
        "aspect_ratio": True,
        "any_replicate_model": True,
        "offline": False,
    }
    best_for = [
        "any image model hosted on Replicate (FLUX, SDXL, Ideogram, Recraft, Imagen, ...) via one token",
        "reusing an existing Replicate account instead of adding a second image provider",
        "provider-neutral image generation with the model chosen per call",
    ]
    not_good_for = ["offline / local-only generation", "fully reproducible deterministic output"]
    fallback_tools = ["flux_image", "openai_image", "recraft_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {
                "type": "string",
                "default": _DEFAULT_MODEL,
                "description": "Any Replicate image model slug (owner/name or owner/name:version).",
            },
            "negative_prompt": {"type": "string"},
            "aspect_ratio": {"type": "string", "default": "16:9"},
            "width": {"type": "integer", "description": "Overrides aspect_ratio for models that take pixel sizes (e.g. SDXL)."},
            "height": {"type": "integer"},
            "num_outputs": {"type": "integer", "default": 1, "minimum": 1, "maximum": 4},
            "output_format": {"type": "string", "enum": ["png", "jpg", "webp"], "default": "png"},
            "seed": {"type": "integer"},
            "extra_input": {
                "type": "object",
                "description": "Passthrough for model-specific inputs; merged last, overrides defaults.",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "aspect_ratio", "width", "height", "seed"]
    side_effects = ["writes image file(s) to output_path", "calls Replicate API"]
    user_visible_verification = ["Inspect generated image for relevance and quality"]

    def _get_api_token(self) -> str | None:
        return os.environ.get("REPLICATE_API_TOKEN")

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._get_api_token() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        model = inputs.get("model", _DEFAULT_MODEL)
        # Match by slug ignoring any ":version" suffix.
        base = _MODEL_COST.get(model.split(":", 1)[0], 0.03)
        return round(base * max(1, int(inputs.get("num_outputs", 1))), 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        token = self._get_api_token()
        if not token:
            return ToolResult(
                success=False,
                error="REPLICATE_API_TOKEN not set. " + self.install_instructions,
            )

        import requests

        start = time.time()
        model = inputs.get("model", _DEFAULT_MODEL)
        prompt = inputs["prompt"]
        num_outputs = max(1, int(inputs.get("num_outputs", 1)))
        out_fmt = inputs.get("output_format", "png")

        model_input: dict[str, Any] = {"prompt": prompt}
        if inputs.get("negative_prompt"):
            model_input["negative_prompt"] = inputs["negative_prompt"]
        if inputs.get("width") and inputs.get("height"):
            model_input["width"] = inputs["width"]
            model_input["height"] = inputs["height"]
        elif inputs.get("aspect_ratio"):
            model_input["aspect_ratio"] = inputs["aspect_ratio"]
        if num_outputs != 1:
            model_input["num_outputs"] = num_outputs
        if out_fmt:
            model_input["output_format"] = out_fmt
        if inputs.get("seed") is not None:
            model_input["seed"] = inputs["seed"]
        # Model-specific passthrough wins over the generic defaults above.
        if isinstance(inputs.get("extra_input"), dict):
            model_input.update(inputs["extra_input"])

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "wait=60",
        }

        try:
            submit = requests.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json={"input": model_input},
                timeout=90,
            )
            submit.raise_for_status()
            pred = submit.json()

            # Prefer: wait may return synchronously; otherwise poll to completion.
            while pred.get("status") in ("starting", "processing"):
                time.sleep(2)
                get_url = pred.get("urls", {}).get("get")
                if not get_url:
                    return ToolResult(success=False, error="Replicate response missing poll URL")
                poll = requests.get(get_url, headers=headers, timeout=30)
                poll.raise_for_status()
                pred = poll.json()

            if pred.get("status") != "succeeded":
                return ToolResult(
                    success=False,
                    error=f"Replicate generation {pred.get('status')}: {pred.get('error')}",
                )

            output = pred.get("output")
            urls = output if isinstance(output, list) else [output]
            urls = [u for u in urls if isinstance(u, str)]
            if not urls:
                return ToolResult(success=False, error=f"Unexpected output shape from Replicate: {output!r}")

            ext = out_fmt if out_fmt in _IMAGE_EXTS else "png"
            base = Path(inputs.get("output_path") or f"replicate_image_output.{ext}")
            base.parent.mkdir(parents=True, exist_ok=True)

            saved: list[str] = []
            for i, url in enumerate(urls):
                target = base if i == 0 else base.with_name(f"{base.stem}_{i}{base.suffix or '.' + ext}")
                img = requests.get(url, timeout=120)
                img.raise_for_status()
                target.write_bytes(img.content)
                saved.append(str(target))

        except Exception as e:
            return ToolResult(success=False, error=f"Replicate image generation failed: {e}")

        return ToolResult(
            success=True,
            data={
                "provider": "replicate",
                "model": model,
                "prompt": prompt,
                "output": saved[0],
                "outputs": saved,
                "seed": pred.get("input", {}).get("seed", inputs.get("seed")),
            },
            artifacts=saved,
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            seed=inputs.get("seed"),
            model=model,
        )
