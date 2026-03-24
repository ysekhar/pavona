# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""Shared runtime helpers for pyUVM sequences."""

from __future__ import annotations

import logging
from typing import Optional

import cocotb
from pyuvm import uvm_sequence

from .dv_base_core_report import dv_base_core_report
from .dv_verbosity import UVM_LOW


class dv_base_sequence_core(uvm_sequence):
    """Common sequence runtime: logger plumbing and spawned-task ownership."""

    def __init__(self, name: str = "dv_base_sequence_core") -> None:
        super().__init__(name)
        self.logger: logging.Logger = logging.getLogger(self.get_name())
        self.reporting = dv_base_core_report(self, parent=None, default_verbosity=UVM_LOW)
        self.uvm_verbosity: int = self.reporting.verbosity
        self.uvm_report = self.reporting.uvm_report
        self._spawned_tasks: dict[int, tuple[str, cocotb.task.Task]] = {}

    def spawn_task(self, coro, name: Optional[str] = None):
        task = cocotb.start_soon(coro)
        task_name = name or getattr(coro, "__name__", f"{self.get_name()}_task")
        self._spawned_tasks[id(task)] = (task_name, task)
        return task

    async def cancel_spawned_tasks(self) -> None:
        for key, (_, task) in list(self._spawned_tasks.items()):
            if not task.done():
                task.cancel()
            self._spawned_tasks.pop(key, None)

    def bind_logger_from_sequencer(self) -> None:
        sequencer = getattr(self, "sequencer", None)
        if sequencer is None:
            return
        seqr_logger = getattr(sequencer, "logger", None)
        seqr_verbosity = getattr(sequencer, "uvm_verbosity", None)
        if seqr_logger is not None:
            self.logger = seqr_logger
            self.reporting.set_logger(self.logger)
            self.uvm_report = self.reporting.uvm_report
        if seqr_verbosity is not None:
            self.uvm_verbosity = self.reporting.set_verbosity(int(seqr_verbosity))
            self.uvm_report = self.reporting.uvm_report
