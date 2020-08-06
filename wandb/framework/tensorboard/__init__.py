"""
wandb framework tensorboard module.
"""

from .monkeypatch import patch
from .log import log, tf_summary_to_dict, reset_state

__all__ = ["patch"]
