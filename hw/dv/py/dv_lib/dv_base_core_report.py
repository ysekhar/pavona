# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""Composed reporting helper for DV base classes.

This helper is intentionally composition-only so it does not affect pyUVM type
identity, construction, or factory-visible inheritance.
"""

from __future__ import annotations

from typing import Any, Optional

from .dv_verbosity import UVM_LOW, UvmReporter, resolve_uvm_verbosity


class dv_base_core_report:
    """Owns logger, effective verbosity, and the bound UVM reporter."""

    def __init__(
        self,
        owner: Any,
        parent: Optional[Any] = None,
        default_verbosity: int = UVM_LOW,
    ) -> None:
        self.owner = owner
        self.logger = getattr(owner, "logger")
        inherited = getattr(parent, "uvm_verbosity", default_verbosity)
        self.verbosity: int = int(inherited)
        self.uvm_report = UvmReporter(self.logger, self.verbosity)

    def apply_cfg(self, cfg: Optional[Any] = None) -> int:
        """Resolve effective verbosity with an optional cfg override."""
        self.verbosity = resolve_uvm_verbosity(self.verbosity, cfg)
        self.uvm_report.set_logger(self.logger)
        self.uvm_report.set_verbosity(self.verbosity)
        return self.verbosity

    def set_verbosity(self, verbosity: int) -> int:
        self.verbosity = int(verbosity)
        self.uvm_report.set_verbosity(self.verbosity)
        return self.verbosity

    def set_logger(self, logger: Any) -> None:
        self.logger = logger
        self.uvm_report.set_logger(logger)
