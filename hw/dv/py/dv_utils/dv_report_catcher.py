# Copyright zeroRISC Inc.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

"""Report catcher/demoter utility.

Python port of SV ``dv_report_catcher``:
- stores severity rewrites keyed by report ID and message regex
- applies rewrites when the report ID exists and regex matches message text
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Dict, Tuple


class report_action_e(str, Enum):
    """Mirror UVM catcher action enum values used by this utility."""

    THROW = "THROW"


@dataclass
class dv_report_message:
    """Report payload passed to ``dv_report_catcher.catch()``."""

    report_id: str
    message: str
    severity: Any


class dv_report_catcher:
    """
    Port of SV ``dv_report_catcher``.

    The API mirrors the SV methods:
    - ``add_change_sev(id, msg, sev)``
    - ``remove_change_sev(id, msg="")``
    - ``catch(report)``
    """

    def __init__(self, name: str = "dv_report_catcher") -> None:
        self.name = name
        self._changed_sev: Dict[str, Dict[str, Any]] = {}

    def catch(self, report: dv_report_message) -> report_action_e:
        """
        Apply severity rewrite rules to a report in-place.

        Returns ``THROW`` to mirror SV behavior: let report continue after mutation.
        """
        for key in (report.report_id, "*"):
            rules = self._changed_sev.get(key)
            if rules is None:
                continue
            for msg_regex, severity in rules.items():
                if re.search(msg_regex, report.message):
                    report.severity = severity
        return report_action_e.THROW

    def add_change_sev(self, report_id: str, msg: str, sev: Any) -> None:
        """Change severity for reports with matching ID and message regex."""
        self._changed_sev.setdefault(report_id, {})[msg] = sev

    def remove_change_sev(self, report_id: str, msg: str = "") -> None:
        """
        Remove a severity change entry.

        If ``msg == ""``, remove all rules for the report ID.
        """
        if report_id not in self._changed_sev:
            return

        if msg == "":
            del self._changed_sev[report_id]
            return

        self._changed_sev[report_id].pop(msg, None)
        if not self._changed_sev[report_id]:
            del self._changed_sev[report_id]

    def catch_fields(
        self,
        report_id: str,
        message: str,
        severity: Any,
    ) -> Tuple[report_action_e, Any]:
        """
        Convenience wrapper for call sites that pass raw fields.

        Returns:
        - action (always ``THROW``)
        - possibly rewritten severity
        """
        report = dv_report_message(report_id=report_id, message=message, severity=severity)
        action = self.catch(report)
        return action, report.severity
