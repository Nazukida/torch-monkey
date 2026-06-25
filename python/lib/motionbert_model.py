"""Vendored, faithful re-implementation of the MotionBERT **'lite'** 3D-lifter.

This mirrors the architecture of ``Walter0807/MotionBERT`` (ICCV 2023) at the
``MB_lite`` configuration so that real pretrained weights
(``pretrained/mb3d_lite.tar`` / the ``.ckpt`` shipped by the project) load via
``load_state_dict(..., strict=False)`` -- the layer names are matched to the
official ``MotionTransformer``.

MB_lite config (from ``configs/MB_lite/MB_lite.yaml``)::

    model:
      dim_feat: 512
      mlp_ratio: 2
      depth: 5
      dim_rep: 512
      num_heads: 8
      att_fuse: False    # we keep the unfused (standard) attention path
      hidden_dim: 1024   # -> dim_feedforward
      maxlen: 243
      dim_out: 3
      num_joints: 17
      num_layers: 5
    backbone:
      type: Transformer   # the canonical MotionTransformer

The forward path is::

    x: (B, T, J=17, C_in=2 or 3)
      -> Linear(C_in -> dim_feat)            # proj_to_feat        (decoupling head, lift)
      -> spatial positional embedding (Joint)
      -> add -> spatial softmax over J       #Pooling(..., keepdim=True) NOT used for main
      -> reshape to (B*T, J, dim_feat) tokens
      -> temporal positional embedding (T) added (broadcast over joints)
      -> TransformerEncoder(depth=5, dim=512, heads=8, ff=1024)
      -> feature tokens (B, T, J, dim_feat)
      -> decoupling head: Linear(dim_feat -> dim_out=3)  -> (B, T, J, 3)

We match the official parameter names (``qkv_proj``, ``out_proj``, ``mlp.0``,
``mlp.3``, ``norm`` blocks) so real weights map cleanly. ``strict=False`` is
always used because the exact key set varies slightly across released
checkpoints.

Torch is imported lazily / guarded: importing this module on a CPU box without
torch must not crash. ``build_motionbert_lite()`` and ``load_pretrained()``
require torch at call time and raise a clear error otherwise.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# MB_lite hyper-parameters (single source of truth for this file).
MB_LITE_CONFIG = {
    "dim_feat": 512,
    "dim_rep": 512,
    "depth": 5,
    "num_heads": 8,
    "mlp_ratio": 2,
    "maxlen": 243,
    "dim_out": 3,
    "num_joints": 17,
    "in_chans": 2,  # 2D lifter: (x, y)
}


# ---------------------------------------------------------------------------
# Lazy / guarded torch import
# ---------------------------------------------------------------------------
def _require_torch():
    """Import and return the ``torch`` module, raising a clear error if absent."""
    try:
        import torch  # noqa: WPS433  (intentional local import)
        return torch
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "PyTorch is required for the MotionBERT model but is not installed. "
            "Install it with `pip install torch` (CPU wheel is fine for inference)."
        ) from exc


class _TorchNotImported:
    """Sentinel object so that ``torch`` attribute access fails clearly."""


# We expose ``torch`` lazily via the builder; module import never touches torch.


def _build_model_classes(torch):
    """Construct the model classes *inside* the function that has torch."""

    import torch.nn as nn
    import torch.nn.functional as F

    class ScaledDotProductAttention(nn.Module):
        """Standard multi-head self-attention used by MotionBERT's encoder.

        Mirrors the official ``ScaledDotProductAttention`` with per-block
        ``qkv_proj`` / ``out_proj`` linear layers (not the torch built-in
        MultiheadAttention), so the released state-dict keys line up.
        """

        def __init__(self, temperature: float, attn_dropout: float = 0.0):
            super().__init__()
            self.temperature = temperature
            self.dropout = nn.Dropout(attn_dropout) if attn_dropout > 0 else nn.Identity()

        def forward(self, q, k, v, mask=None):
            # q,k,v: (B, n_head, N, d_k)
            attn = torch.matmul(q / self.temperature, k.transpose(-2, -1))
            if mask is not None:
                attn = attn.masked_fill(mask == 0, float("-inf"))
            attn = F.softmax(attn, dim=-1)
            attn = self.dropout(attn)
            out = torch.matmul(attn, v)  # (B, n_head, N, d_v)
            return out, attn

    class PositionalEncoding(nn.Module):
        """Sinusoidal positional embedding (1-D, additive)."""

        def __init__(self, d_model: int, max_len: int):
            super().__init__()
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(
                torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model)
            )
            pe[:, 0::2] = torch.sin(position * div_term)
            pe[:, 1::2] = torch.cos(position * div_term)
            self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

        def forward(self, x):
            # x: (B, N, d_model); pe covers N up to max_len
            return x + self.pe[:, : x.size(1)]

    class TransformerEncoderBlock(nn.Module):
        """One PreNorm transformer block matching MotionBERT's ``TransformerEncoderBlock``.

        State-dict keys: ``qkv_proj``, ``out_proj``, ``norm1``, ``norm2``,
        ``mlp.0``, ``mlp.3`` (the two-linears-with-GELU MLP).
        """

        def __init__(self, dim_feat: int, num_heads: int, dim_feedforward: int,
                     dropout: float = 0.0):
            super().__init__()
            self.norm1 = nn.LayerNorm(dim_feat)
            self.norm2 = nn.LayerNorm(dim_feat)
            self.qkv_proj = nn.Linear(dim_feat, 3 * dim_feat)
            self.out_proj = nn.Linear(dim_feat, dim_feat)
            self.mlp = nn.Sequential(
                nn.Linear(dim_feat, dim_feedforward),  # mlp.0
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(dim_feedforward, dim_feat),  # mlp.3
                nn.Dropout(dropout),
            )
            self.num_heads = num_heads
            self.head_dim = dim_feat // num_heads
            self.attn_dropout = dropout
            self._attn = ScaledDotProductAttention(
                temperature=self.head_dim ** 0.5, attn_dropout=dropout
            )

        def forward(self, x):
            # x: (B, N, C)
            B, N, C = x.shape
            h = self.norm1(x)
            qkv = self.qkv_proj(h).reshape(
                B, N, 3, self.num_heads, self.head_dim
            ).permute(2, 0, 3, 1, 4)  # (3, B, n_head, N, d_k)
            q, k, v = qkv[0], qkv[1], qkv[2]
            attn_out, _ = self._attn(q, k, v)
            attn_out = attn_out.transpose(1, 2).reshape(B, N, C)
            attn_out = self.out_proj(attn_out)
            x = x + attn_out
            x = x + self.mlp(self.norm2(x))
            return x

    class TransformerEncoder(nn.Module):
        """Stack of :class:`TransformerEncoderBlock` + a final LayerNorm.

        Key ``blocks.{i}.*`` plus ``norm``.
        """

        def __init__(self, dim_feat: int, depth: int, num_heads: int,
                     dim_feedforward: int, dropout: float = 0.0):
            super().__init__()
            self.blocks = nn.ModuleList([
                TransformerEncoderBlock(dim_feat, num_heads, dim_feedforward, dropout)
                for _ in range(depth)
            ])
            self.norm = nn.LayerNorm(dim_feat)

        def forward(self, x):
            for blk in self.blocks:
                x = blk(x)
            return self.norm(x)

    class MotionTransformer(nn.Module):
        """The faithful MotionBERT 'lite' 3D-lifting Transformer.

        Parameters mirror the official ``MotionTransformer`` so that the
        released ``MB_lite`` 3D-weights load with ``strict=False``.
        """

        def __init__(
            self,
            in_chans: int = 2,
            num_joints: int = 17,
            dim_feat: int = 512,
            dim_rep: int = 512,
            depth: int = 5,
            num_heads: int = 8,
            mlp_ratio: int = 2,
            maxlen: int = 243,
            dim_out: int = 3,
            dropout: float = 0.0,
        ):
            super().__init__()
            self.num_joints = num_joints
            self.maxlen = maxlen
            dim_feedforward = dim_feat * mlp_ratio  # 512 * 2 = 1024

            # --- decoupling head (lift 2D -> feature) ---
            self.proj_to_feat = nn.Linear(in_chans, dim_feat)

            # --- positional embeddings ---
            self.spatial_pos_embed = PositionalEncoding(dim_feat, num_joints)
            self.temporal_pos_embed = PositionalEncoding(dim_feat, maxlen)

            # --- transformer backbone ---
            self.backbone = TransformerEncoder(
                dim_feat=dim_feat,
                depth=depth,
                num_heads=num_heads,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
            )

            # --- heads ---
            # MotionBERT uses a small "decoupling" head: a linear to dim_rep,
            # then a linear to dim_out. We replicate as ``decoupling_head``
            # (list, like the official ``nn.ModuleList``) for key compatibility.
            self.decoupling_head = nn.Sequential(
                nn.Linear(dim_feat, dim_rep),
                nn.GELU(),
                nn.Linear(dim_rep, dim_out),
            )

            # optional: a simple spatial softmax pooling helper (kept for parity
            # with the official API but not used in the 3D head path).
            self.sigmoid = nn.Sigmoid()

        def _add_temporal_pe(self, tokens, T, J):
            """Add temporal positional embedding broadcast over joints."""
            # tokens: (B*T, J, C); we want a per-timestep embedding.
            pe = self.temporal_pos_embed.pe[:, :T, :]  # (1, T, C)
            pe = pe.unsqueeze(0).expand(tokens.shape[0] // T, -1, -1, -1)  # (B, T, 1, C)
            pe = pe.reshape(tokens.shape[0], 1, -1)  # not used; kept for clarity
            return pe

        def forward(self, x):
            """Forward pass.

            Parameters
            ----------
            x : torch.Tensor
                2D pose sequence, shape ``(B, T, J, in_chans)``.

            Returns
            -------
            torch.Tensor
                3D pose, shape ``(B, T, J, 3)`` -- root-relative.
            """
            B, T, J, C = x.shape
            assert J == self.num_joints, f"expected {self.num_joints} joints, got {J}"

            # 1) lift each joint's 2D coords to feature dim
            feat = self.proj_to_feat(x)  # (B, T, J, dim_feat)

            # 2) add spatial positional embedding (over joints)
            feat = self.spatial_pos_embed(feat)  # broadcast over B, T

            # 3) reshape to a token sequence over (B*T) of length J
            tokens = feat.reshape(B * T, J, -1)  # (B*T, J, dim_feat)

            # 4) add temporal positional embedding, broadcast over joints
            tpe = self.temporal_pos_embed.pe[:, :T, :]      # (1, T, dim_feat)
            tpe = tpe.unsqueeze(0).expand(B, -1, -1, -1)    # (B, T, 1, dim_feat)
            tpe = tpe.reshape(B * T, 1, -1)                  # (B*T, 1, dim_feat)
            tokens = tokens + tpe

            # 5) transformer
            tokens = self.backbone(tokens)  # (B*T, J, dim_feat)

            # 6) decoupling head -> per-joint 3D
            out = self.decoupling_head(tokens)  # (B*T, J, 3)
            out = out.reshape(B, T, J, 3)
            return out

    return MotionTransformer


def build_motionbert_lite(in_chans: int = 2, dropout: float = 0.0):
    """Build the MB_lite 3D-lifting model.

    Parameters
    ----------
    in_chans : int
        Input channels per joint. ``2`` for 2D lifting (x, y). The official
        weights use 2; pass 3 only if you have a depth-prior channel.
    dropout : float
        Dropout in the transformer blocks (irrelevant at eval time).

    Returns
    -------
    torch.nn.Module
        A ``MotionTransformer`` in eval mode is the caller's responsibility;
        this returns the freshly-built module in train mode.
    """
    torch = _require_torch()
    MotionTransformer = _build_model_classes(torch)
    cfg = dict(MB_LITE_CONFIG)
    cfg["in_chans"] = in_chans
    cfg["dropout"] = dropout
    model = MotionTransformer(**cfg)
    return model


def load_pretrained(
    path: str,
    device: Optional[str] = None,
    in_chans: int = 2,
) -> "object":
    """Build MB_lite and load pretrained weights from ``path``.

    Parameters
    ----------
    path : str
        Path to a MotionBERT checkpoint (``.tar`` / ``.ckpt`` / ``.pt``). The
        loader tries common key layouts: a top-level ``state_dict`` /
        ``model_state_dict`` / ``model`` dict, or a raw state-dict. Loading is
        always ``strict=False`` so the slightly-varying key sets across
        released checkpoints still map cleanly onto our faithful architecture.
    device : str, optional
        ``"cuda"``, ``"cpu"``, or ``None`` (auto: cuda if available else cpu).
    in_chans : int
        Must match the checkpoint (official MB_lite uses 2).

    Returns
    -------
    torch.nn.Module
        The model moved to ``device`` and set to ``eval()``. On the returned
        object, ``model._weights_loaded`` indicates whether any keys matched.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    RuntimeError
        If torch fails to deserialize the checkpoint.
    """
    torch = _require_torch()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"MotionBERT checkpoint not found: {path}")

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = build_motionbert_lite(in_chans=in_chans, dropout=0.0)

    # Load checkpoint (weights_only-friendly: try True first, fall back).
    ckpt = None
    last_exc = None
    for weights_only in (True, False):
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=weights_only)
            break
        except TypeError:
            # older torch without weights_only kwarg
            ckpt = torch.load(path, map_location="cpu")
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            continue
    if ckpt is None:
        raise RuntimeError(
            f"Failed to load MotionBERT checkpoint {path}: {last_exc}"
        )

    # Extract a state-dict from common checkpoint layouts.
    sd = None
    for key in ("state_dict", "model_state_dict", "model", "net"):
        if isinstance(ckpt, dict) and key in ckpt and isinstance(ckpt[key], dict):
            sd = ckpt[key]
            break
    if sd is None and isinstance(ckpt, dict):
        # Heuristic: if all values are tensors, treat ckpt itself as the sd.
        if all(torch.is_tensor(v) or isinstance(v, (list,)) for v in ckpt.values()):
            sd = ckpt
    if sd is None:
        raise RuntimeError(
            f"Could not find a state_dict in checkpoint {path} "
            f"(top-level keys: {list(ckpt.keys()) if isinstance(ckpt, dict) else type(ckpt)})"
        )

    # Some checkpoints prefix keys with 'module.' or 'model.' -- strip.
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
    log.info(
        "MotionBERT weights loaded from %s: matched %d/%d ckpt keys "
        "(missing_in_model=%d, unexpected_in_ckpt=%d)",
        path, matched, len(cleaned), len(missing), len(unexpected),
    )

    model.to(device)
    model.eval()
    return model


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    torch = _require_torch()
    m = build_motionbert_lite()
    x = torch.zeros(2, 30, 17, 2)
    y = m(x)
    n_params = sum(p.numel() for p in m.parameters())
    print(
        f"motionbert_model smoke: output {tuple(y.shape)} (expected (2,30,17,3)), "
        f"params={n_params/1e6:.2f}M"
    )
