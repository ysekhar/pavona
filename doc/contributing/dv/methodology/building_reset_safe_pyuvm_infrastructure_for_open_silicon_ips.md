# Building Reset-Safe pyUVM Infrastructure for Open Silicon IPs

Author(s): [Yogish Sekhar](mailto:ycsekhar@zerorisc.com)
Last Updated: June 14, 2026

**TL;DR:**
Pavona's pyUVM reset management follows the same Stop-Clean-Restart methodology
used by the SystemVerilog UVM infrastructure, but maps it to Python coroutines,
cocotb tasks, and pyUVM sequences. Reset is driven through a dedicated
`clk_rst_agent`, observed through a `dv_rst_domain`, and handled by reset-aware
base classes for drivers, monitors, agents, scoreboards, sequencers, and virtual
sequences.

# Introduction

pyUVM gives Pavona a Python-native route for writing UVM-style testbenches on top
of cocotb. The value is not only the language change. Python makes it easier to
share reference models, inspect complex data structures, and build small
verification environments without SystemVerilog macro overhead.

The reset problem does not disappear in Python. A reset can still invalidate an
in-flight transaction, leave a sequence waiting for a response that will never
arrive, or cause a scoreboard to compare pre-reset expectations against
post-reset DUT behavior. The pyUVM infrastructure on this branch makes reset
safety a framework-level behavior instead of asking every test to rediscover it.

This document extracts the reset management work from the pyUVM branch and
documents how to build and port pyUVM testbenches that follow the Pavona reset
methodology.

# Design Goal

The core goal is the same as the SV-UVM reset-safe infrastructure:

* Reset is controlled from one place.
* All components can observe reset through a reset-domain abstraction.
* In-flight protocol state is stopped and cleaned when reset asserts.
* Transaction generation restarts only after reset deasserts and the DUT has
  completed any required post-reset initialization.
* Tests can enable random or directed mid-test reset without writing ad-hoc reset
  logic in every sequence.

The pyUVM implementation uses Python async tasks instead of SV `process` handles.
The conceptual structure remains the same:

```
Stop   : cancel active cocotb tasks and stop non-exempt pyUVM sequences
Clean  : drive interface signals idle and clear local queues/bookkeeping
Restart: wait for reset deassertion, run dut_init(), and start stimulus again
```

# Repository Orientation

The pyUVM reset-safe infrastructure lives under `hw/dv/py`.

| Area | Key files | Reset responsibility |
|------|-----------|----------------------|
| Clock/reset interface | `interfaces/clk_rst_if.py` | Drives `clk`/`rst_n`, applies reset, and provides clock/reset waits. |
| Reset domain | `dv_lib/dv_rst_domain.py` | Wraps `ClkRstIf` with polarity-abstract `wait_reset_assert()` and `wait_reset_deassert()` APIs. |
| Reset agent | `clk_rst_agent/` | Owns reset-driving sequences, reset monitor, and delay sequencing. |
| Base driver | `dv_lib/dv_base_driver.py` | Cancels the active drive task on reset and calls `reset_interface_and_driver()`. |
| Base monitor | `dv_lib/dv_base_monitor.py` | Cancels the active collection task on reset and calls `reset_monitor()`. |
| Base agent | `dv_lib/dv_base_agent.py` | Watches reset and stops non-exempt sequencers. |
| Base sequencer | `dv_lib/dv_base_sequencer.py` | Tracks spawned sequences, cancels them, and flushes queues on reset. |
| Base virtual sequencer | `dv_lib/dv_base_virtual_sequencer.py` | Marks virtual sequencers as reset-exempt. |
| Base virtual sequence | `dv_lib/dv_base_vseq.py` | Owns the reset loop, random-reset trigger, `main_thread()`, and `dut_init()` flow. |
| Base scoreboard | `dv_lib/dv_base_scoreboard.py` | Watches reset, resets RAL models, and clears shared outstanding CSR bookkeeping. |
| Example environment | `tl_agent/dv/` | Demonstrates reset-safe TL driver, monitor, scoreboard, test, and vseq wiring. |

# Reset Domains

A reset domain is a region of the DUT and testbench synchronized by the same
reset signal. In the pyUVM infrastructure, a domain is represented by
`dv_rst_domain`, which wraps a `ClkRstIf`.

`ClkRstIf` owns the pin-level details:

* Clock period, frequency, duty cycle, jitter, and scaling.
* Active-low reset driving through `rst_n`.
* Reset application through `apply_reset()`.
* Clock and reset synchronization through cocotb triggers.

`dv_rst_domain` owns the methodology contract:

* `wait_reset_assert()` waits for assertion and supports asynchronous assert.
* `wait_reset_deassert()` waits for synchronous deassertion on the domain clock.
* `apply_reset()` routes reset control through the bound clock/reset interface.
* `is_driving_reset()` lets reset-driving components know whether this interface
  is the active reset owner.

All reset-aware components should depend on `cfg.reset_domain`, not on raw
`rst_n` edges. This keeps reset polarity, clock alignment, and future multi-domain
support localized to the reset-domain layer.

# Structural Testbench Elements

pyUVM keeps the familiar UVM separation between structural components and dynamic
sequence objects.

| Element | Base class | Reset-safe behavior |
|---------|------------|---------------------|
| Test | `dv_base_test` | Creates config/env, starts the requested virtual sequence, and applies the initial POR in the TL example test. |
| Environment | `dv_base_env` | Creates virtual sequencer, scoreboard, optional coverage, and env-specific agents. |
| Agent | `dv_base_agent` | Builds monitor/driver/sequencer and starts a reset monitor that calls `stop_sequences()` on reset. |
| Driver | `dv_base_driver` | Waits for POR, starts `get_and_drive()`, cancels it on reset, then restarts it after deassertion. |
| Monitor | `dv_base_monitor` | Waits for POR, starts `collect_trans()`, cancels it on reset, then restarts it after deassertion. |
| Sequencer | `dv_base_sequencer` | Tracks active sequence tasks and flushes sequence/FIFO queues during `stop_sequences()`. |
| Virtual sequencer | `dv_base_virtual_sequencer` | Has `do_not_reset = True` because the master virtual sequence controls reset. |
| Scoreboard | `dv_base_scoreboard` | Monitors reset and resets shared model state; derived scoreboards must clear protocol-specific queues. |

# Dynamic Testbench Elements

| Element | Class or file | Reset-safe behavior |
|---------|---------------|---------------------|
| Reset item | `clk_rst_agent/clk_rst_item.py` | Encodes `APPLY_RESET`, `DELAY`, `RESET_ASSERTED`, and `RESET_DEASSERTED` operations. |
| Reset sequence | `clk_rst_agent/seq_lib/reset_seq.py` | Sends an `APPLY_RESET` item to the clock/reset sequencer. |
| Delay sequence | `clk_rst_agent/seq_lib/delay_seq.py` | Sends a `DELAY` item and waits for a response after the delay driver counts clock cycles. |
| Test parameters | `dv_lib/dv_test_seq_parameters.py` | Randomized once per test and frozen; controls reset testing and reset loop count. |
| Config parameters | `dv_lib/dv_config_parameters.py` | Recreated and randomized once per reset-to-reset operational window. |
| Virtual sequence | `dv_lib/dv_base_vseq.py` | Runs reset monitoring, `reset_trigger_thread()`, `dut_init()`, and `main_thread()` in the right order. |

# Reset-Aware pyUVM Flow

The pyUVM reset flow is built around cocotb task cancellation and pyUVM sequence
stopping.

```
1. Test build_phase()
   - Create ClkRstIf.
   - Create dv_rst_domain.
   - Assign reset_domain and vif handles into env/agent cfg objects.

2. Env build/connect
   - Instantiate protocol agents, clk_rst_agent, delay_agent, virtual sequencer,
     and scoreboard.
   - Connect protocol monitor analysis ports into the scoreboard.
   - Put clk_rst_sequencer and delay_sequencer handles on the virtual sequencer.

3. POR
   - The active reset owner applies reset at the start of the test.
   - In the current TL example, POR is applied explicitly in the test run_phase().
   - Mid-test resets are driven through reset_seq and clk_rst_agent.
   - Drivers, monitors, agents, scoreboards, and vseqs wait for a full assert and
     deassert cycle before functional stimulus starts.

4. Normal operation
   - dv_base_vseq.body() creates/freeze-randomizes test_params.
   - For each reset loop, it creates and randomizes config_params.
   - dut_init() runs after reset deassertion if enabled.
   - reset_trigger_thread() and main_thread() run concurrently.

5. Mid-test reset
   - reset_trigger_thread() normally delays, then starts reset_seq on the
     clk_rst_sequencer.
   - dv_base_vseq waits until reset assertion is observed.
   - Agents stop non-exempt sequencers.
   - Drivers cancel get_and_drive() and return pins/state to idle.
   - Monitors cancel collect_trans() and clear partial observation state.
   - Scoreboards clear reset-sensitive model state.

6. Restart
   - Components wait for reset deassertion.
   - The vseq creates new config_params, runs dut_init(), and starts a fresh
     main_thread() for the next operational window.
```

# Clock and Reset Agent

The reset signal should only be driven through the clock/reset infrastructure.
The main pieces are:

* `clk_rst_item`: shared reset/delay sequence item.
* `reset_seq`: sends `APPLY_RESET`.
* `clk_rst_driver`: delegates `APPLY_RESET` to `reset_domain.apply_reset()`.
* `clk_rst_monitor`: publishes `RESET_ASSERTED` and `RESET_DEASSERTED` items
  when it observes reset transitions.
* `delay_seq` and `delay_driver`: provide clock-cycle delay services used by
  random-reset virtual sequences.
* `clk_rst_agent`: sets its sequencer's `do_not_reset` flag so the reset-driving
  sequence is not cancelled by the agent reset monitor.

The reset agent is special because it is both an agent and the mechanism that
creates reset. Its sequencer must be reset-exempt. If it is stopped during reset,
the sequence that is trying to complete reset can be cancelled, leaving the test
stuck in reset.

For a new environment, pick exactly one POR owner. Do not let multiple testbench
components independently drive the same reset pin. The POR path and the mid-test
reset path should both go through the same `ClkRstIf` and `dv_rst_domain`.

# Signal Layer: Drivers

All protocol drivers should extend `dv_base_driver`. A derived driver supplies
two hooks:

* `get_and_drive()`: the normal forever loop that fetches transactions and drives
  pins.
* `reset_interface_and_driver()`: the cleanup hook that drives outputs idle and
  clears driver-owned state.

The base class owns the reset behavior:

1. Wait for POR assertion.
2. Call `reset_interface_and_driver()`.
3. Wait for POR deassertion.
4. Start `_reset_monitor_task()` and `get_and_drive()` as cocotb tasks.
5. When reset asserts, cancel `get_and_drive()`.
6. Clear the `processing_item` flag and wait for reset deassertion.
7. Restart `get_and_drive()`.

Driver rules:

* Use `await self.get_next_item()` rather than directly calling
  `seq_item_port.get_next_item()`.
* Call `self.item_done()` when the item is fully handled or deliberately aborted.
* Keep reset detection out of `get_and_drive()`.
* Put all pin cleanup and local queue cleanup in `reset_interface_and_driver()`.
* Any child tasks spawned by `get_and_drive()` must be cancelled in a `finally`
  block or from `reset_interface_and_driver()`.

The TL host driver is the reference pattern. It starts A-channel, D-channel, and
ready-response tasks from `get_and_drive()`, keeps the parent coroutine alive with
an event, and cancels those child tasks in `finally`. Its reset hook invalidates
the A channel, drives `d_ready` low, clears `pending_a_req`, and records that
reset was asserted.

```python
async def get_and_drive(self):
    await self.wait_for_clk()
    self._a_task = cocotb.start_soon(self.a_channel_thread())
    self._d_task = cocotb.start_soon(self.d_channel_thread())
    stopper = Event()
    try:
        await stopper.wait()
    finally:
        for task in (self._a_task, self._d_task):
            if task is not None and not task.done():
                task.cancel()

def reset_interface_and_driver(self):
    self.invalidate_a_channel()
    self.vif.d_ready.value = 0
    self.pending_a_req.clear()
```

# Signal Layer: Monitors

All protocol monitors should extend `dv_base_monitor`. A derived monitor supplies
two hooks:

* `collect_trans()`: the normal observation loop.
* `reset_monitor()`: cleanup for partial transactions and monitor-owned pending
  state.

The base monitor follows the same task pattern as the driver. It waits for POR,
starts a reset monitor task and `collect_trans()`, cancels `collect_trans()` on
reset assertion, and restarts collection after reset deassertion.

Monitor rules:

* Do not publish transactions during reset.
* Clear partial transaction buffers in `reset_monitor()`.
* If coverage needs to know whether work was pending at reset, sample that before
  clearing state.
* Use the base `notify()` helper when subscribers need both callbacks and
  analysis-port writes.

The TL monitor is the reference pattern. Its reset hook samples
`pending_req_on_rst` coverage, clears `pending_a_req`, and clears the shared
`a_source_pend_q` if present. Its channel collectors only emit transactions on
completed `valid && ready` handshakes.

# Transaction Layer: Agents and Sequencers

`dv_base_agent` makes the transaction layer reset-aware. After POR, it starts an
agent reset task that waits for reset assertion and stops active sequences on the
agent's sequencer unless the sequencer has `do_not_reset = True`.

`dv_base_sequencer.stop_sequences()`:

* Cancels active tasks registered through `start_sequence()` or
  `spawn_sequence()`.
* Clears the active sequence task registry.
* Flushes pyUVM sequence queues and optional analysis FIFOs.

Sequencer rules:

* Protocol sequencers should usually be resettable.
* Virtual sequencers should not be resettable.
* The clock/reset sequencer must not be resettable.
* Long-running background sequences should be launched with `spawn_sequence()` so
  the sequencer can track and cancel them on reset.

# Scenario Layer: Virtual Sequences

`dv_base_vseq` is the center of reset-safe stimulus. Derived virtual sequences
should not override `body()`. Instead they implement:

* `dut_init()`: optional post-reset DUT setup.
* `reset_trigger_thread()`: the reset generator for reset-testing loops.
* `main_thread()`: the functional stimulus for one reset-to-reset interval.

The base `body()` does this:

1. Bind cfg, coverage, RAL, logger, and virtual sequencer handles.
2. Create and randomize `test_params`.
3. Freeze `test_params`.
4. Start background reset monitoring.
5. For each reset loop:
   * Create and randomize new `config_params`.
   * Wait for reset deassertion if the DUT is currently in reset.
   * Run `dut_init()` if enabled.
   * Start `reset_trigger_thread()` and `main_thread()` concurrently.
   * Wait for the reset thread iteration.
   * If reset testing is enabled and more loops remain, cancel `main_thread()`.
   * Otherwise wait for `main_thread()` to complete.

The important split is that `main_thread()` is reset-free. It should express
functional intent only. `reset_trigger_thread()` decides when to reset and drives
reset through `reset_seq`.

The TL base virtual sequence is the reference pattern:

* `reset_trigger_thread()` reads `config_params.rand_reset_delay`, runs a
  `delay_seq`, then starts `reset_seq` on `clk_rst_sequencer_h`.
* `main_thread()` starts the device responder sequence, waits long enough for the
  DUT to be active, then runs host traffic.
* The `finally` block stops the device sequence so normal completion and reset
  cancellation clean up the same way.

Directed reset tests can override `reset_trigger_thread()` when the reset must
land on a specific protocol condition. The `tl_agent_pending_reset_vseq` example
starts delayed device responses, launches a burst of host requests, waits 10
cycles, and then triggers reset while requests are pending.

# Test Parameters and Config Parameters

The framework deliberately separates test-stable parameters from per-reset-window
parameters.

| Parameter class | Lifetime | Purpose |
|-----------------|----------|---------|
| `dv_test_seq_parameters` | Randomized once at test start, then frozen | Controls the overall test shape: reset testing, number of reset loops, transaction count, and whether `dut_init()`/`dut_shutdown()` run. |
| `dv_config_parameters` | Created and randomized once per reset loop | Controls the DUT configuration for the current operational window. |

Rule of thumb:

* If the value must survive reset, put it in `TEST_PARAMS_CLS`.
* If the value describes only the current post-reset configuration, put it in
  `CONFIG_PARAMS_CLS`.

For example, the TL environment uses `tl_agent_test_seq_parameters` for test-wide
control and `tl_agent_config_parameters` for random reset delay and TL traffic
shape in a single reset window.

# Scoreboards and RAL

`dv_base_scoreboard` monitors `cfg.reset_domain`. On reset assertion/deassertion
it:

* Logs that reset occurred.
* Calls `reset()` after deassertion.
* Resets every RAL model registered in `cfg.ral_models`.
* Calls the Python CSR outstanding-access cleanup hook when available.

This is intentionally generic. Derived scoreboards must still reset their own
protocol-specific state, including:

* Expected and actual queues.
* Pending request maps.
* In-order comparison buffers.
* In-flight memory or CSR prediction records.
* Any analysis FIFO readers or background tasks that can keep stale state.

For protocol scoreboards, override `reset()` and call `super().reset(kind)` before
clearing local state.

```python
def reset(self, kind: str = "HARD"):
    super().reset(kind)
    self._queue_src.clear()
    self._queue_dst.clear()
```

Do not rely on the base scoreboard to know protocol-specific queue names. If a
pre-reset expectation remains in a derived scoreboard, the next post-reset
transaction can produce a false mismatch.

# Environment and Test Wiring

A reset-safe pyUVM testbench needs the following wiring.

In the test:

* Create `ClkRstIf`.
* Configure its clock period/frequency.
* Call `set_active(drive_clk_val=True, drive_rst_n_val=True)` for the active
  reset owner.
* Create `dv_rst_domain(clk_rst_if, name=...)`.
* Create protocol interface wrappers with the same clock and reset.
* Assign `cfg.reset_domain`.
* Assign every agent cfg's `vif` and `reset_domain`.
* Apply the initial POR through the same reset interface or clock/reset agent.

The TL base test shows the pattern:

```python
self.clk_rst_if = ClkRstIf(tb_top, self.logger)
self.clk_rst_if.set_period_ps(10_000)
self.clk_rst_if.set_active(drive_clk_val=True, drive_rst_n_val=True)

reset_domain = dv_rst_domain(self.clk_rst_if, name="default_rst_domain")
tl_vif = TlIf(tb_top, prefix="", clk=self.clk_rst_if.clk, rst_n=self.clk_rst_if.rst_n)

self.cfg.reset_domain = reset_domain
self.cfg.clk_rst_cfg.vif = self.clk_rst_if
self.cfg.clk_rst_cfg.reset_domain = reset_domain
self.cfg.delay_cfg.vif = self.clk_rst_if
self.cfg.delay_cfg.reset_domain = reset_domain
self.cfg.host_agent_cfg.vif = tl_vif
self.cfg.host_agent_cfg.reset_domain = reset_domain
self.cfg.device_agent_cfg.vif = tl_vif
self.cfg.device_agent_cfg.reset_domain = reset_domain
```

In the environment:

* Instantiate the protocol agents.
* Instantiate `clk_rst_agent` and `delay_agent`.
* Connect protocol monitor ports to the scoreboard.
* Put sequencer handles on the virtual sequencer:
  * protocol sequencers
  * `clk_rst_sequencer_h`
  * `delay_sequencer_h`

# Reset Coverage

Reset coverage should answer whether the testbench actually exercised meaningful
reset behavior, not just whether reset toggled.

Useful coverage points include:

* Reset asserted during idle.
* Reset asserted with pending protocol requests.
* Reset asserted with pending responses.
* Reset asserted during each major DUT configuration mode.
* Reset deassertion followed by successful post-reset CSR/default checks.
* Reset loops completed without stale scoreboard mismatches.

The TL monitor demonstrates a protocol-specific coverage point:
`m_pending_req_on_rst_cg` samples whether A-channel requests were pending when
reset asserted.

# Porting Checklist

Use this checklist when moving an existing pyUVM testbench onto the reset-safe
framework.

| Step | Action |
|------|--------|
| 1 | Create a `ClkRstIf` and `dv_rst_domain` in the test. |
| 2 | Put `reset_domain` on the env cfg and on every agent cfg. |
| 3 | Convert protocol drivers to extend `dv_base_driver`. |
| 4 | Implement driver `get_and_drive()` and `reset_interface_and_driver()`. |
| 5 | Convert protocol monitors to extend `dv_base_monitor`. |
| 6 | Implement monitor `collect_trans()` and `reset_monitor()`. |
| 7 | Convert protocol agents to extend `dv_base_agent`. |
| 8 | Ensure protocol sequencers are resettable and virtual/clock-reset sequencers are reset-exempt. |
| 9 | Use `start_sequence()` or `spawn_sequence()` so active sequence tasks are tracked. |
| 10 | Create an env virtual sequencer derived from `dv_base_virtual_sequencer`. |
| 11 | Put protocol, clock/reset, and delay sequencer handles on the virtual sequencer. |
| 12 | Create a base vseq derived from `dv_base_vseq`. |
| 13 | Implement `dut_init()`, `reset_trigger_thread()`, and `main_thread()`. |
| 14 | Clear scoreboard protocol queues on reset. |
| 15 | Add reset coverage points that prove reset occurred during meaningful DUT activity. |
| 16 | Run at least one deterministic reset test and one random-reset-loop test. |

# Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Calling `seq_item_port.get_next_item()` directly | Use the base driver's `await self.get_next_item()` wrapper. |
| Forgetting `item_done()` | Ensure every handled or aborted item calls `self.item_done()` before the driver loop moves on. |
| Reset logic inside `main_thread()` | Keep `main_thread()` reset-free; use `reset_trigger_thread()` for reset generation. |
| Not cancelling child cocotb tasks | Cancel child tasks in `finally` blocks or reset hooks. |
| Resetting the clock/reset sequencer | Ensure `clk_rst_agent` leaves `sequencer.do_not_reset = True`. |
| Starting background sequences without tracking them | Use `spawn_sequence()` on `dv_base_sequencer`. |
| Leaving monitor pending state alive | Clear protocol maps, partial items, and shared cfg queues in `reset_monitor()`. |
| Leaving scoreboard queues alive | Override `reset()` in derived scoreboards and clear all expected/actual queues. |
| Using raw reset edges throughout the bench | Use `cfg.reset_domain.wait_reset_assert()` and `wait_reset_deassert()`. |
| Treating config params as test params | Put per-reset-window state in `CONFIG_PARAMS_CLS`, not in the test or env cfg. |

# Worked Example: TileLink Agent

The TL pyUVM environment is the current worked example.

| Concern | Reference implementation |
|---------|--------------------------|
| Test-level reset domain creation | `hw/dv/py/tl_agent/dv/tests/tl_agent_base_test.py` |
| Env agent and virtual sequencer wiring | `hw/dv/py/tl_agent/dv/env/tl_agent_env.py` |
| Virtual sequencer handles | `hw/dv/py/tl_agent/dv/env/tl_agent_virtual_sequencer.py` |
| Random reset virtual sequence | `hw/dv/py/tl_agent/dv/env/seq_lib/tl_agent_base_vseq.py` |
| Pending-request reset test | `hw/dv/py/tl_agent/dv/env/seq_lib/tl_agent_pending_reset_vseq.py` |
| Host driver cleanup | `hw/dv/py/tl_agent/tl_host_driver.py` |
| Device driver cleanup | `hw/dv/py/tl_agent/tl_device_driver.py` |
| Monitor pending-state cleanup and reset coverage | `hw/dv/py/tl_agent/tl_monitor.py` |
| Scoreboard wiring | `hw/dv/py/tl_agent/dv/env/tl_agent_scoreboard.py` |

The TL pending-reset test is the most useful reset-specific example. It holds
device responses off long enough to create pending requests, then asserts reset.
This exercises the full Stop-Clean-Restart path:

* The host and device sequencers are stopped.
* The host driver clears pending A-channel requests.
* The device driver invalidates D-channel outputs.
* The monitor samples pending-request-on-reset coverage and clears its pending
  map.
* The virtual sequence is cancelled and restarted by `dv_base_vseq.body()`.

# Validation

A pyUVM reset-safe port is not complete until these checks pass.

| Check | Pass criterion |
|-------|----------------|
| POR completes | Drivers, monitors, agents, scoreboard, and vseq all observe reset assert/deassert before stimulus. |
| Driver idle during reset | Waveforms show every driver-owned output returned to idle values while reset is active. |
| Monitor quiet during reset | No protocol transactions are written during reset. |
| Mid-test reset completes | A reset asserted during active traffic does not hang simulation. |
| Sequence cancellation works | Non-exempt protocol sequencers have no stale active sequence tasks after reset. |
| Virtual sequence survives | The master virtual sequence is not stopped by an agent reset thread. |
| Scoreboard does not compare stale data | No mismatches caused by pre-reset expected items after reset deassertion. |
| Config params refresh | Per-window config randomization occurs once per reset loop. |
| Test params stay stable | Test-level reset knobs are randomized once and remain stable across loops. |
| Coverage samples reset scenarios | Reset coverage distinguishes idle reset from reset with useful in-flight activity. |

# Further Reading

* [Building Scalable System Verilog UVM Infrastructure for Open Silicon IPs](./building_scalable_system_verilog_uvm_infrastructure_for_open_silicon_ips.md)
* [Pavona DV Reset-Safe Testbench Porting Guide](./pavona_reset_safe_porting_guide.md)
* [Reset Management in Design Verification Testbenches](../../../../rfc/rfc-2026-01-DV-Reset-Management/rfc_2026_01_dv_reset_management.md)
* `hw/dv/py/dv_lib/dv_base_vseq.py`
* `hw/dv/py/dv_lib/dv_base_driver.py`
* `hw/dv/py/dv_lib/dv_base_monitor.py`
* `hw/dv/py/dv_lib/dv_base_agent.py`
* `hw/dv/py/clk_rst_agent/`
