# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""
Base scoreboard for pyUVM DV environments.

This ports the common reset and abort behavior from the SystemVerilog
dv_base_scoreboard:
- mirror the primary RAL handle from cfg during build
- watch reset assertions/deassertions during run
- reset all registered RAL models on reset
- optionally invoke check_phase() from pre_abort() when a fatal happens during
  run_phase(), matching the SV debug aid
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

import cocotb
from pyuvm import ConfigDB, uvm_component

from .dv_base_core_report import dv_base_core_report
from .dv_base_env_cfg import dv_base_env_cfg
from .dv_verbosity import UVM_LOW


RAL_T = TypeVar("RAL_T", bound=Any)
CFG_T = TypeVar("CFG_T", bound=dv_base_env_cfg)
COV_T = TypeVar("COV_T")


class dv_base_scoreboard(uvm_component, Generic[RAL_T, CFG_T, COV_T]):
    """Base scoreboard with reset monitoring and debug-friendly abort behavior."""

    def __init__(self, name: str, parent: Optional[uvm_component] = None):
        super().__init__(name, parent)
        self.cfg: Optional[CFG_T] = None
        self.ral: Optional[RAL_T] = None
        self.cov: Optional[COV_T] = None

        self.obj_raised: bool = False
        self.under_pre_abort: bool = False

        self._monitor_reset_task: Optional[cocotb.Task] = None
        self._sample_resets_task: Optional[cocotb.Task] = None
        self._in_run_phase: bool = False
        self.reporting = dv_base_core_report(self, parent=parent, default_verbosity=UVM_LOW)
        self.uvm_verbosity: int = self.reporting.verbosity
        self.uvm_report = self.reporting.uvm_report

    def build_phase(self):
        super().build_phase()
        if self.cfg is None:
            self.cfg = ConfigDB().get(self, "", "cfg")
        if self.cfg is None:
            self.uvm_report.fatal(self.get_name(), f"failed to get cfg from ConfigDB")
        self.uvm_verbosity = self.reporting.apply_cfg(self.cfg)
        self.uvm_report = self.reporting.uvm_report
        self.ral = getattr(self.cfg, "ral", None)

    async def run_phase(self):
        await super().run_phase()

        if self.cfg is None or getattr(self.cfg, "reset_domain", None) is None:
            self.uvm_report.fatal(self.get_name(), f"cfg.reset_domain == None")

        self._in_run_phase = True
        self._monitor_reset_task = cocotb.start_soon(self.monitor_reset())
        self._sample_resets_task = cocotb.start_soon(self.sample_resets())

    async def monitor_reset(self):
        """Watch reset transitions and synchronize scoreboard state to them."""
        assert self.cfg is not None
        reset_domain = self.cfg.reset_domain

        while True:
            await reset_domain.wait_reset_assert()
            self.uvm_report.info(self.get_name(), f"reset occurred", UVM_LOW)

            await reset_domain.wait_reset_deassert()
            self.reset()

            self._clear_outstanding_access()
            self.uvm_report.info(self.get_name(), f"out of reset", UVM_LOW)

    async def sample_resets(self):
        """Override in derived scoreboards when reset coverage collection is needed."""
        return

    def reset(self, kind: str = "HARD"):
        """Reset every RAL model registered in the environment config."""
        if self.cfg is None:
            return

        for ral_model in getattr(self.cfg, "ral_models", {}).values():
            if ral_model is None:
                continue
            reset_fn = getattr(ral_model, "reset", None)
            if callable(reset_fn):
                reset_fn(kind)

    def pre_abort(self):
        """
        Run check_phase() on fatal aborts that happen during run_phase().

        This mirrors the SV behavior that keeps scoreboard checks alive after a
        fatal, which can provide more useful debug information.
        """
        super_pre_abort = getattr(super(), "pre_abort", None)
        if callable(super_pre_abort):
            super_pre_abort()

        if self.under_pre_abort or not self._in_run_phase:
            return

        check_phase = getattr(self, "check_phase", None)
        if not callable(check_phase):
            return

        self.under_pre_abort = True
        try:
            check_phase()
        finally:
            self.under_pre_abort = False

    def _clear_outstanding_access(self):
        """
        Best-effort hook for CSR access bookkeeping cleanup.

        The SV code calls csr_utils_pkg::clear_outstanding_access(). Python
        support for that package is optional, so tolerate it being absent.
        """
        try:
            from . import csr_utils_pkg  # type: ignore
        except ImportError:
            return

        clear_fn = getattr(csr_utils_pkg, "clear_outstanding_access", None)
        if callable(clear_fn):
            clear_fn()
