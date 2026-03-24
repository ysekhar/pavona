# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""Base pyUVM test."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import Generic, Optional, Type, TypeVar, cast

import cocotb
import vsc
from cocotb.triggers import Timer, with_timeout
from cocotb.task import CancelledError
from pyuvm import ConfigDB, uvm_component, uvm_sequence, uvm_test

from .dv_base_env import dv_base_env
from .dv_base_core_report import dv_base_core_report
from .dv_base_env_cfg import dv_base_env_cfg
from .dv_cocotb_utils import get_plusarg
from dv_utils.dv_report_manager import DvReportManager, DvReportPolicy
from .dv_verbosity import UVM_LOW, UVM_MEDIUM, parse_uvm_verbosity


CFG_T = TypeVar("CFG_T", bound=dv_base_env_cfg)
ENV_T = TypeVar("ENV_T", bound=uvm_component)


class dv_base_test(uvm_test, Generic[CFG_T, ENV_T]):
    """Python port of SV ``dv_base_test``."""

    CFG_CLS: Type[dv_base_env_cfg] = dv_base_env_cfg
    ENV_CLS: Type[uvm_component] = dv_base_env

    def __init__(self, name: str, parent: Optional[uvm_component] = None):
        super().__init__(name, parent)
        self.env: Optional[ENV_T] = None
        self.cfg: Optional[CFG_T] = None
        self.test_seq_s: str = ""

        self.max_quit_count: int = 1
        self.test_timeout_ns: int = 200_000_000
        self.drain_time_ns: int = 0
        self.print_char_len: int = 80
        self.print_topology: bool = False

        self.reporting = dv_base_core_report(self, parent=parent, default_verbosity=UVM_LOW)
        self.uvm_verbosity: int = self.reporting.verbosity
        self.uvm_report = self.reporting.uvm_report
        self.report_manager: Optional[DvReportManager] = None

        self._poll_for_stop_task: Optional[cocotb.Task] = None
        self._coverage_export_done: bool = False

    def build_phase(self):
        super().build_phase()

        self.uvm_verbosity = parse_uvm_verbosity(self._get_str_arg("UVM_VERBOSITY", "LOW"))
        self.reporting.set_verbosity(self.uvm_verbosity)
        self.max_quit_count = self._get_int_arg("max_quit_count", self.max_quit_count)
        self.print_char_len = self._get_int_arg("print_char_len", self.print_char_len)
        policy = DvReportPolicy(
            fail_on_warning=self._parse_bool_text(
                self._get_str_arg("UVM_FAIL_ON_WARNING", "0"), False
            ),
            fail_on_error=self._parse_bool_text(
                self._get_str_arg("UVM_FAIL_ON_ERROR", "1"), True
            ),
            fail_on_fatal=self._parse_bool_text(
                self._get_str_arg("UVM_FAIL_ON_FATAL", "1"), True
            ),
            max_quit_count=self.max_quit_count,
        )
        self.report_manager = DvReportManager.create(
            root_logger=self.logger,
            verbosity=self.uvm_verbosity,
            policy=policy,
            print_char_len=self.print_char_len,
        )
        if self.report_manager is None:
            raise RuntimeError(f"{self.get_name()}: failed to initialize report_manager")
        self.reporting.set_logger(self.logger)
        self.reporting.set_verbosity(self.uvm_verbosity)
        self.uvm_report = self.reporting.uvm_report
        self.add_message_demotes(self.report_manager.catcher)

        self.env = cast(ENV_T, self.ENV_CLS("env", self))
        self.cfg = cast(CFG_T, self.CFG_CLS("cfg"))
        if hasattr(self.cfg, "uvm_verbosity") and getattr(self.cfg, "uvm_verbosity") is None:
            setattr(self.cfg, "uvm_verbosity", self.uvm_verbosity)

        self.cfg.initialize()
        if not self.cfg.randomize():
            self.uvm_report.fatal(self.get_name(), f"cfg randomization failed")

        self.test_timeout_ns = self._get_int_arg("test_timeout_ns", self.test_timeout_ns)
        self.cfg.en_scb = self._get_bool_arg("en_scb", self.cfg.en_scb)
        self.cfg.en_scb_tl_err_chk = self._get_bool_arg(
            "en_scb_tl_err_chk", self.cfg.en_scb_tl_err_chk
        )
        self.cfg.en_scb_mem_chk = self._get_bool_arg("en_scb_mem_chk", self.cfg.en_scb_mem_chk)
        self.cfg.zero_delays = self._get_bool_arg("zero_delays", self.cfg.zero_delays)
        self.cfg.en_cov = self._get_bool_arg("en_cov", self.cfg.en_cov)

        self.print_topology = self._get_bool_arg("print_topology", self.print_topology)
        self.reporting.set_logger(self.logger)
        self.reporting.set_verbosity(self.uvm_verbosity)
        self.uvm_report = self.reporting.uvm_report

        self.env.cfg = self.cfg
        if hasattr(self.env, "reporting"):
            self.env.reporting.set_logger(self.env.logger)
            self.env.uvm_verbosity = self.env.reporting.set_verbosity(self.uvm_verbosity)
            self.env.uvm_report = self.env.reporting.uvm_report
        elif hasattr(self.env, "uvm_report"):
            self.env.uvm_report.set_logger(self.env.logger)
            self.env.uvm_report.set_verbosity(self.uvm_verbosity)
            self.env.uvm_verbosity = self.uvm_verbosity


    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()

        if self.print_topology:
            print(self.get_full_name())

    async def run_phase(self):
        self.uvm_report.info(self.get_name(), "run_phase()", UVM_LOW)
        await super().run_phase()

        self.drain_time_ns = self._get_int_arg("drain_time_ns", self.drain_time_ns)
        self.test_seq_s = self._get_str_arg("UVM_TEST_SEQ", self.test_seq_s)

        if self.test_seq_s == "":
            self.uvm_report.fatal(self.get_name(), f"UVM_TEST_SEQ was not provided")

        self.raise_objection()
        try:
            self.uvm_report.info(self.get_name(), "calling run_seq()", UVM_LOW)
            await with_timeout(self.run_seq(self.test_seq_s), self.test_timeout_ns, "ns")

            if self.drain_time_ns > 0:
                await Timer(self.drain_time_ns, unit="ns")
        finally:
            self.drop_objection()
            self.report_manager.shutdown()

    def report_phase(self):
        super().report_phase()
        self.report_manager.log_summary(self.logger)
        self._export_coverage_if_enabled()
        fail_msg = self.report_manager.log_final_status(self.logger, self.get_name())

        if fail_msg is not None:
            # Fail once from report phase; cocotb/pyuvm will report the failure line.
            raise AssertionError(fail_msg) from None

    def add_message_demotes(self, catcher) -> None:
        """Override in derived tests to install message demotes/severity rewrites."""
        del catcher

    async def run_seq(self, test_seq_s: str) -> None:
        if self.env is None:
            self.uvm_report.fatal(self.get_name(), f"env was not created")
        if not test_seq_s:
            self.uvm_report.fatal(self.get_name(), f"UVM_TEST_SEQ is empty; set it to a Python sequence class path"
            )

        test_seq = self.create_seq_by_name(test_seq_s)
        test_seq.logger = self.logger
        setattr(test_seq, "uvm_verbosity", self.uvm_verbosity)
        if hasattr(test_seq, "uvm_report"):
            test_seq.uvm_report.set_logger(self.logger)
            test_seq.uvm_report.set_verbosity(self.uvm_verbosity)
        self.configure_sequence(test_seq)

        randomize = getattr(test_seq, "randomize", None)
        if callable(randomize) and not randomize():
            self.uvm_report.fatal(self.get_name(), f"sequence randomization failed for {test_seq_s}")

        self.uvm_report.info(self.get_name(), f"Starting test sequence {test_seq_s}",
            UVM_MEDIUM,
        )
        virtual_sequencer = getattr(self.env, "virtual_sequencer", None)
        if virtual_sequencer is None:
            self.uvm_report.fatal(self.get_name(), f"env.virtual_sequencer is required")
        await virtual_sequencer.start_sequence(test_seq)
        self.uvm_report.info(self.get_name(), f"Finished test sequence {test_seq_s}",
            UVM_MEDIUM,
        )

    def configure_sequence(self, seq: uvm_sequence) -> None:
        if self.env is None:
            self.uvm_report.fatal(self.get_name(), f"env was not created")

        virtual_sequencer = getattr(self.env, "virtual_sequencer", None)
        if virtual_sequencer is None:
            self.uvm_report.fatal(self.get_name(), f"env.virtual_sequencer is required")

        set_sequencer = getattr(seq, "set_sequencer", None)
        if callable(set_sequencer):
            set_sequencer(virtual_sequencer)
        else:
            setattr(seq, "sequencer", virtual_sequencer)

    def create_seq_by_name(self, name: str) -> uvm_sequence:
        module_name: str
        class_name: str
        if ":" in name:
            module_name, class_name = name.split(":", 1)
        else:
            module_name, _, class_name = name.rpartition(".")
        if not module_name or not class_name:
            raise RuntimeError(f"{self.get_name()}: cannot resolve sequence name '{name}'")

        cls = getattr(import_module(module_name), class_name)
        seq = cls()
        if not isinstance(seq, uvm_sequence):
            raise RuntimeError(f"{self.get_name()}: '{name}' is not a uvm_sequence")
        return seq

    async def _poll_for_stop(self, filename: str = "dv.stop") -> None:
        stop_file = Path(filename)
        while True:
            if stop_file.exists():
                self.uvm_report.fatal(self.get_name(), f"found stop file '{filename}'")
            await Timer(self.poll_for_stop_interval_ns, unit="ns")

    def _get_str_arg(self, name: str, default: str) -> str:
        cocotb_val = get_plusarg(name)
        if cocotb_val is not None:
            return cocotb_val
        return os.getenv(name, default)

    def _get_int_arg(self, name: str, default: int) -> int:
        value = self._get_str_arg(name, str(default))
        try:
            return int(value, 0)
        except ValueError:
            self.uvm_report.warning(self.get_name(), f"could not parse integer argument {name}='{value}', using {default}"
            )
            return default

    def _get_bool_arg(self, name: str, default: bool) -> bool:
        value = self._get_str_arg(name, "1" if default else "0").strip().lower()
        parsed = self._parse_bool_text(value, None)
        if parsed is not None:
            return parsed
        self.uvm_report.warning(self.get_name(), f"could not parse boolean argument {name}='{value}', using {default}"
        )
        return default

    def _export_coverage_if_enabled(self) -> None:
        if self._coverage_export_done:
            return
        self._coverage_export_done = True

        if self.cfg is None or not getattr(self.cfg, "en_cov", False):
            return

        output_path = self._get_str_arg("PYVSC_COV_DB", "").strip()
        if not output_path:
            output_path = str(Path.cwd() / "cov_db.xml")

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            vsc.write_coverage_db(output_path, fmt="xml")
            self.uvm_report.info(self.get_name(), f"wrote pyvsc coverage database to {output_path}",
                UVM_MEDIUM,
            )
        except Exception as err:
            self.uvm_report.warning(self.get_name(), f"failed to write pyvsc coverage database '{output_path}': {err}"
            )

    @staticmethod
    def _parse_bool_text(value: str, default: Optional[bool]) -> Optional[bool]:
        text = str(value).strip().lower()
        if text in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "f", "no", "n", "off"}:
            return False
        return default
