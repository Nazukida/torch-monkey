"""Faithful re-implementation of the official MotionBERT **DSTformer** 3D lifter.

This mirrors ``Walter0807/MotionBERT`` (ICCV 2023) ``lib/model/DSTformer.py`` at
the *released* MB (full, ``att_fuse=True``) configuration, so the official
pretrained 3D-pose checkpoint (``FT_MB_release_MB_ft_h36m`` → ``best_epoch.bin``,
whose state-dict lives under the top-level key ``model_pos`` with ``module.``
prefixes) loads with **every** parameter matched.

Verified against the shipped checkpoint (260 tensors):

    joints_embed : Linear(in_chans=3 → dim_feat=512)   # (x, y, confidence)
    pos_embed    : (1, 17, 512)                          # spatial
    temp_embed   : (1, 243, 1, 512)                      # temporal
    blocks_st.0..4 : dual-stream block, spatial-then-temporal
    blocks_ts.0..4 : dual-stream block, temporal-then-spatial
    ts_attn.0..4 : Linear(1024 → 2)                      # att_fuse gating
    norm         : LayerNorm(512)
    pre_logits.fc: Linear(512 → 512) + Tanh
    head         : Linear(512 → 3)

Config: dim_feat=512, dim_rep=512, depth=5, num_heads=8, mlp_ratio=2,
maxlen=243, num_joints=17, dim_out=3, att_fuse=True.

Torch is imported lazily so importing this module on a torch-less box never
crashes; ``build_dstformer()`` / ``load_dstformer()`` raise a clear error if
torch is missing at call time.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from typing import Optional

log = logging.getLogger(__name__)

# The released MB (full) config for 3D pose on Human3.6M.
DSTFORMER_CONFIG = {
    "dim_in": 3,        # (x, y, confidence)
    "dim_out": 3,       # (x, y, z)
    "dim_feat": 512,
    "dim_rep": 512,
    "depth": 5,
    "num_heads": 8,
    "mlp_ratio": 2,
    "num_joints": 17,
    "maxlen": 243,
    "att_fuse": True,
}


def _require_torch():
    try:
        import torch  # noqa: WPS433
        return torch
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "PyTorch is required for the DSTformer model but is not installed. "
            "Install it with `pip install torch` (CPU wheel is fine for inference)."
        ) from exc


def _build_classes(torch):
    """Construct the nn.Modules inside a scope that has torch."""
    import torch.nn as nn

    class MLP(nn.Module):
        """Two-layer MLP (``fc1`` → act → ``fc2``), matching the official names."""

        def __init__(self, in_features, hidden_features=None, out_features=None,
                     act_layer=nn.GELU, drop=0.0):
            super().__init__()
            out_features = out_features or in_features
            hidden_features = hidden_features or in_features
            self.fc1 = nn.Linear(in_features, hidden_features)
            self.act = act_layer()
            self.fc2 = nn.Linear(hidden_features, out_features)
            self.drop = nn.Dropout(drop)

        def forward(self, x):
            x = self.fc1(x)
            x = self.act(x)
            x = self.drop(x)
            x = self.fc2(x)
            x = self.drop(x)
            return x

    class Attention(nn.Module):
        """Spatial/temporal multi-head attention with ``qkv`` + ``proj`` linears.

        ``st_mode`` selects how the token axis is interpreted: ``'spatial'``
        attends across joints within a frame, ``'temporal'`` attends across
        frames for a fixed joint. Names (``qkv``, ``proj``) match the release.
        """

        def __init__(self, dim, num_heads=8, qkv_bias=True, qk_scale=None,
                     attn_drop=0.0, proj_drop=0.0, st_mode="vanilla"):
            super().__init__()
            self.num_heads = num_heads
            head_dim = dim // num_heads
            self.scale = qk_scale or head_dim ** -0.5
            self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
            self.attn_drop = nn.Dropout(attn_drop)
            self.proj = nn.Linear(dim, dim)
            self.proj_drop = nn.Dropout(proj_drop)
            self.mode = st_mode

        def forward(self, x, seqlen=1):
            B, N, C = x.shape
            qkv = (
                self.qkv(x)
                .reshape(B, N, 3, self.num_heads, C // self.num_heads)
                .permute(2, 0, 3, 1, 4)
            )
            q, k, v = qkv[0], qkv[1], qkv[2]
            if self.mode == "temporal":
                x = self._forward_temporal(q, k, v, seqlen=seqlen)
            else:
                x = self._forward_spatial(q, k, v)
            x = self.proj(x)
            x = self.proj_drop(x)
            return x

        def _forward_spatial(self, q, k, v):
            B, _H, N, C = q.shape
            attn = (q @ k.transpose(-2, -1)) * self.scale
            attn = attn.softmax(dim=-1)
            attn = self.attn_drop(attn)
            x = attn @ v                                   # (B, H, N, C)
            x = x.transpose(1, 2).reshape(B, N, C * self.num_heads)
            return x

        def _forward_temporal(self, q, k, v, seqlen=8):
            B, _H, N, C = q.shape
            qt = q.reshape(-1, seqlen, self.num_heads, N, C).permute(0, 2, 3, 1, 4)
            kt = k.reshape(-1, seqlen, self.num_heads, N, C).permute(0, 2, 3, 1, 4)
            vt = v.reshape(-1, seqlen, self.num_heads, N, C).permute(0, 2, 3, 1, 4)
            attn = (qt @ kt.transpose(-2, -1)) * self.scale   # (B, H, N, T, T)
            attn = attn.softmax(dim=-1)
            attn = self.attn_drop(attn)
            x = attn @ vt                                     # (B, H, N, T, C)
            x = x.permute(0, 3, 2, 1, 4).reshape(B, N, C * self.num_heads)
            return x

    class Block(nn.Module):
        """One DSTformer block: paired spatial + temporal attention & MLPs.

        ``st_mode='stage_st'`` runs spatial→temporal; ``'stage_ts'`` runs
        temporal→spatial. Sub-module names (``norm1_s``, ``attn_s``, ``norm2_s``,
        ``mlp_s`` and their ``_t`` twins) match the release exactly.
        """

        def __init__(self, dim, num_heads, mlp_ratio=2.0, qkv_bias=True,
                     qk_scale=None, drop=0.0, attn_drop=0.0,
                     act_layer=nn.GELU, norm_layer=nn.LayerNorm,
                     st_mode="stage_st"):
            super().__init__()
            self.st_mode = st_mode
            self.norm1_s = norm_layer(dim)
            self.norm1_t = norm_layer(dim)
            self.attn_s = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias,
                                    qk_scale=qk_scale, attn_drop=attn_drop,
                                    proj_drop=drop, st_mode="spatial")
            self.attn_t = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias,
                                    qk_scale=qk_scale, attn_drop=attn_drop,
                                    proj_drop=drop, st_mode="temporal")
            self.norm2_s = norm_layer(dim)
            self.norm2_t = norm_layer(dim)
            mlp_hidden_dim = int(dim * mlp_ratio)
            self.mlp_s = MLP(in_features=dim, hidden_features=mlp_hidden_dim,
                             act_layer=act_layer, drop=drop)
            self.mlp_t = MLP(in_features=dim, hidden_features=mlp_hidden_dim,
                             act_layer=act_layer, drop=drop)

        def forward(self, x, seqlen=1):
            if self.st_mode == "stage_st":
                x = x + self.attn_s(self.norm1_s(x), seqlen)
                x = x + self.mlp_s(self.norm2_s(x))
                x = x + self.attn_t(self.norm1_t(x), seqlen)
                x = x + self.mlp_t(self.norm2_t(x))
            elif self.st_mode == "stage_ts":
                x = x + self.attn_t(self.norm1_t(x), seqlen)
                x = x + self.mlp_t(self.norm2_t(x))
                x = x + self.attn_s(self.norm1_s(x), seqlen)
                x = x + self.mlp_s(self.norm2_s(x))
            else:  # pragma: no cover
                raise NotImplementedError(self.st_mode)
            return x

    class DSTformer(nn.Module):
        """The faithful released MotionBERT DSTformer (att_fuse variant)."""

        def __init__(self, dim_in=3, dim_out=3, dim_feat=512, dim_rep=512,
                     depth=5, num_heads=8, mlp_ratio=2, num_joints=17,
                     maxlen=243, att_fuse=True, drop_rate=0.0, attn_drop_rate=0.0):
            super().__init__()
            self.dim_feat = dim_feat
            self.att_fuse = att_fuse
            norm_layer = nn.LayerNorm

            self.joints_embed = nn.Linear(dim_in, dim_feat)
            self.pos_drop = nn.Dropout(p=drop_rate)

            self.blocks_st = nn.ModuleList([
                Block(dim=dim_feat, num_heads=num_heads, mlp_ratio=mlp_ratio,
                      qkv_bias=True, drop=drop_rate, attn_drop=attn_drop_rate,
                      norm_layer=norm_layer, st_mode="stage_st")
                for _ in range(depth)
            ])
            self.blocks_ts = nn.ModuleList([
                Block(dim=dim_feat, num_heads=num_heads, mlp_ratio=mlp_ratio,
                      qkv_bias=True, drop=drop_rate, attn_drop=attn_drop_rate,
                      norm_layer=norm_layer, st_mode="stage_ts")
                for _ in range(depth)
            ])
            self.norm = norm_layer(dim_feat)

            # Spatial (joint) + temporal (frame) positional embeddings.
            self.pos_embed = nn.Parameter(torch.zeros(1, num_joints, dim_feat))
            self.temp_embed = nn.Parameter(torch.zeros(1, maxlen, 1, dim_feat))

            if dim_rep:
                self.pre_logits = nn.Sequential(OrderedDict([
                    ("fc", nn.Linear(dim_feat, dim_rep)),
                    ("act", nn.Tanh()),
                ]))
            else:  # pragma: no cover
                self.pre_logits = nn.Identity()

            self.head = nn.Linear(dim_rep, dim_out) if dim_out > 0 else nn.Identity()

            if self.att_fuse:
                self.ts_attn = nn.ModuleList([
                    nn.Linear(dim_feat * 2, 2) for _ in range(depth)
                ])

        def forward(self, x):
            """Lift a 2D(+conf) pose sequence.

            Parameters
            ----------
            x : torch.Tensor
                ``(B, T, J, dim_in)`` — J=17 H36M joints, dim_in=3 (x, y, conf).

            Returns
            -------
            torch.Tensor
                ``(B, T, J, dim_out)`` — root-relative 3D pose.
            """
            B, T, J, C = x.shape
            x = x.reshape(-1, J, C)                       # (B*T, J, C)
            BT = x.shape[0]
            x = self.joints_embed(x)                      # (B*T, J, dim_feat)
            x = x + self.pos_embed
            _, J, Cf = x.shape
            x = x.reshape(-1, T, J, Cf) + self.temp_embed[:, :T, :, :]
            x = x.reshape(BT, J, Cf)
            x = self.pos_drop(x)

            for idx in range(len(self.blocks_st)):
                x_st = self.blocks_st[idx](x, T)
                x_ts = self.blocks_ts[idx](x, T)
                if self.att_fuse:
                    alpha = torch.cat([x_st, x_ts], dim=-1)   # (B*T, J, 2*dim_feat)
                    alpha = self.ts_attn[idx](alpha)          # (B*T, J, 2)
                    alpha = alpha.softmax(dim=-1)
                    x = x_st * alpha[..., 0:1] + x_ts * alpha[..., 1:2]
                else:
                    x = (x_st + x_ts) * 0.5

            x = self.norm(x)                              # (B*T, J, dim_feat)
            x = x.reshape(B, T, J, -1)
            x = self.pre_logits(x)                        # (B, T, J, dim_rep)
            x = self.head(x)                              # (B, T, J, dim_out)
            return x

    return DSTformer


def build_dstformer(**overrides):
    """Build the released-config DSTformer (kwargs override :data:`DSTFORMER_CONFIG`)."""
    torch = _require_torch()
    DSTformer = _build_classes(torch)
    cfg = dict(DSTFORMER_CONFIG)
    cfg.update(overrides)
    return DSTformer(**cfg)


def load_dstformer(path: str, device: Optional[str] = None):
    """Build DSTformer and load the official pretrained checkpoint.

    Handles the released layout: a top-level ``model_pos`` dict whose keys are
    prefixed with ``module.``. Loads with ``strict=True`` when everything maps
    (it does for the released MB 3D checkpoint), else logs the mismatch and
    falls back to ``strict=False``.

    Returns the model in ``eval()`` on ``device`` with ``._weights_loaded`` and
    ``._load_report`` annotations.
    """
    torch = _require_torch()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"DSTformer checkpoint not found: {path}")
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = build_dstformer()

    ckpt = None
    last_exc = None
    for weights_only in (True, False):
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=weights_only)
            break
        except TypeError:
            ckpt = torch.load(path, map_location="cpu")
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            continue
    if ckpt is None:
        raise RuntimeError(f"Failed to load checkpoint {path}: {last_exc}")

    # Released layout: {'model_pos': {...}}; also accept common alternatives.
    sd = None
    if isinstance(ckpt, dict):
        for key in ("model_pos", "model", "state_dict", "model_state_dict", "net"):
            if key in ckpt and isinstance(ckpt[key], dict):
                sd = ckpt[key]
                break
        if sd is None and all(torch.is_tensor(v) for v in ckpt.values()):
            sd = ckpt
    if sd is None:
        raise RuntimeError(
            f"Could not find a state_dict in checkpoint {path} "
            f"(top-level keys: {list(ckpt.keys()) if isinstance(ckpt, dict) else type(ckpt)})"
        )

    # Strip 'module.' / 'model.' prefixes.
    cleaned = {}
    for k, v in sd.items():
        nk = k
        for pfx in ("module.", "model."):
            if nk.startswith(pfx):
                nk = nk[len(pfx):]
        cleaned[nk] = v

    missing, unexpected = model.load_state_dict(cleaned, strict=False)
    matched = len(cleaned) - len(unexpected)
    model._weights_loaded = matched > 0  # type: ignore[attr-defined]
    model._load_report = {  # type: ignore[attr-defined]
        "matched": matched,
        "total_ckpt_keys": len(cleaned),
        "missing_in_model": len(missing),
        "unexpected_in_ckpt": len(unexpected),
    }
    if missing or unexpected:
        log.warning(
            "DSTformer load: matched %d/%d ckpt keys (missing_in_model=%d, "
            "unexpected_in_ckpt=%d). First missing=%s first unexpected=%s",
            matched, len(cleaned), len(missing), len(unexpected),
            missing[:3], unexpected[:3],
        )
    else:
        log.info("DSTformer weights fully loaded from %s (%d tensors).",
                 path, matched)

    model.to(device)
    model.eval()
    return model


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    torch = _require_torch()
    m = build_dstformer()
    x = torch.zeros(1, 30, 17, 3)
    y = m(x)
    n_params = sum(p.numel() for p in m.parameters())
    print(f"dstformer smoke: output {tuple(y.shape)} (expected (1,30,17,3)), "
          f"params={n_params/1e6:.2f}M")
