# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""SV-UVM style verbosity helpers and centralized reporter."""

from __future__ import annotations

import logging
from typing import Any, Optional

from dv_utils.dv_report_catcher import dv_report_catcher
from dv_utils.dv_report_manager import DvReportManager

UVM_NONE = 0
UVM_LOW = 100
UVM_MEDIUM = 200
UVM_HIGH = 300
UVM_FULL = 400
UVM_DEBUG = 500

UVM_INFO = "INFO"
UVM_WARNING = "WARNING"
UVM_ERROR = "ERROR"
UVM_FATAL = "FATAL"


_VERBOSITY_MAP = {
    "NONE": UVM_NONE,
    "LOW": UVM_LOW,
    "MEDIUM": UVM_MEDIUM,
    "HIGH": UVM_HIGH,
    "FULL": UVM_FULL,
    "DEBUG": UVM_DEBUG,
}


def parse_uvm_verbosity(raw: Optional[str], default: int = UVM_LOW) -> int:
    """Parse UVM_VERBOSITY from symbolic level or integer string."""
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    key = text.upper()
    if key in _VERBOSITY_MAP:
        return _VERBOSITY_MAP[key]
    try:
        return int(text, 0)
    except ValueError:
        return default


def resolve_uvm_verbosity(inherited: int, cfg: Optional[Any] = None) -> int:
    """Resolve verbosity with optional cfg override."""
    if cfg is None:
        return int(inherited)
    raw = getattr(cfg, "uvm_verbosity", None)
    if raw is None:
        return int(inherited)
    if isinstance(raw, int):
        return int(raw)
    return parse_uvm_verbosity(str(raw), int(inherited))


class UvmReporter:
    """Centralized UVM-style reporter."""

    def __init__(self, logger: logging.Logger, verbosity: int = UVM_LOW) -> None:
        self._logger = logger
        self._verbosity = int(verbosity)
        self._local_catcher = dv_report_catcher("uvm_report_catcher")
        manager = DvReportManager.get_or_none()
        if manager is not None:
            manager.register_logger(logger)

    @property
    def verbosity(self) -> int:
        return self._verbosity

    @property
    def catcher(self) -> dv_report_catcher:
        manager = DvReportManager.get_or_none()
        if manager is not None:
            return manager.catcher
        return self._local_catcher

    def set_logger(self, logger: logging.Logger) -> None:
        self._logger = logger
        manager = DvReportManager.get_or_none()
        if manager is not None:
            manager.register_logger(logger)

    def set_verbosity(self, verbosity: int) -> None:
        self._verbosity = int(verbosity)
        manager = DvReportManager.get_or_none()
        if manager is not None:
            manager.set_verbosity(self._verbosity)

    def should_log(self, msg_verbosity: int = UVM_LOW) -> bool:
        return int(msg_verbosity) <= self._verbosity

    def _emit(self, level: str, msg: str, stacklevel: int = 2) -> None:
        log_fn = getattr(self._logger, level)
        try:
            log_fn(msg, stacklevel=stacklevel)
        except TypeError:
            # Fallback for logger adapters that do not accept stacklevel.
            log_fn(msg)

    def add_change_sev(self, report_id: str, msg_regex: str, sev: Any) -> None:
        manager = DvReportManager.get_or_none()
        if manager is not None:
            manager.add_change_sev(report_id, msg_regex, sev)
        else:
            self._local_catcher.add_change_sev(report_id, msg_regex, sev)

    def remove_change_sev(self, report_id: str, msg_regex: str = "") -> None:
        manager = DvReportManager.get_or_none()
        if manager is not None:
            manager.remove_change_sev(report_id, msg_regex)
        else:
            self._local_catcher.remove_change_sev(report_id, msg_regex)

    def info(self, report_id: str, msg: str, verbosity: int) -> None:
        manager = DvReportManager.get_or_none()
        if manager is None:
            if self.should_log(verbosity):
                self._emit("info", msg, 4)
            return
        manager.emit_uvm(
            UVM_INFO,
            msg,
            report_id=report_id,
            verbosity=verbosity,
            logger=self._logger,
            stacklevel=3,
        )

    def warning(self, report_id: str, msg: str) -> None:
        manager = DvReportManager.get_or_none()
        if manager is None:
            self._emit("warning", msg, 4)
            return
        manager.emit_uvm(UVM_WARNING, msg, report_id=report_id, logger=self._logger, stacklevel=3)

    def error(self, report_id: str, msg: str) -> None:
        manager = DvReportManager.get_or_none()
        if manager is None:
            self._emit("error", msg, 4)
            return
        manager.emit_uvm(UVM_ERROR, msg, report_id=report_id, logger=self._logger, stacklevel=3)

    def fatal(self, report_id: str, msg: str) -> None:
        manager = DvReportManager.get_or_none()
        if manager is None:
            self._emit("critical", msg, 4)
            raise RuntimeError(f"UVM_FATAL: {msg}")
        manager.emit_uvm(UVM_FATAL, msg, report_id=report_id, logger=self._logger, stacklevel=3)
