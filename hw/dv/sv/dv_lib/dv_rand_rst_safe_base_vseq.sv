// Copyright zeroRISC Inc
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0


class dv_rand_rst_safe_base_vseq #(
                     type RAL_T               = dv_base_reg_block,
                     type CFG_T               = dv_base_env_cfg,
                     type COV_T               = dv_base_env_cov,
                     type VIRTUAL_SEQUENCER_T = dv_base_virtual_sequencer) extends uvm_sequence;
  `uvm_object_param_utils(dv_rand_rst_safe_base_vseq #(RAL_T, CFG_T, COV_T, VIRTUAL_SEQUENCER_T))
  `uvm_declare_p_sequencer(VIRTUAL_SEQUENCER_T)

  CFG_T   cfg;
  RAL_T   ral;
  COV_T   cov;

  bit   in_reset = 1;

  dv_test_seq_params  test_params;

  `uvm_object_new

  extern virtual task dut_init();
  extern virtual task dut_shutdown();

  extern virtual function uvm_sequence create_seq_by_name(string name);

  extern virtual task pre_start();
  extern virtual task post_start();


  extern virtual task body();

  extern task monitor_reset();
  extern virtual task reset_trigger_thread (const ref dv_test_seq_params  test_params);
  extern virtual task main_thread (const ref dv_test_seq_params  test_params);

  extern virtual function void handle_reset_assertion ();
endclass


task dv_rand_rst_safe_base_vseq::dut_init();
  // Derived class will need to provide an implementation for DUT initialization once reset is
  // deasserted
endtask


// Use the factory to create a sequence by name and return the resulting uvm_sequence.
//
// The created sequence should be an instance of the class where this function is defined.
// Creating the sequence through this method rather than the underlying function,
// dv_utils_pkg::create_seq_by_name, allows subclasses of dv_base_seq to copy information about
// themselves (such as sequencers or other configuration) to the new sequence.
function uvm_sequence dv_rand_rst_safe_base_vseq::create_seq_by_name(string name);
  return dv_utils_pkg::create_seq_by_name(name);
endfunction


task dv_rand_rst_safe_base_vseq::pre_start();
  super.pre_start();

  `DV_CHECK_NE_FATAL(p_sequencer, null, "Did you forget to call `set_sequencer()`?")
  cfg = p_sequencer.cfg;
  cov = p_sequencer.cov;
  ral = cfg.ral;
endtask

task dv_rand_rst_safe_base_vseq::post_start();
  super.post_start();
  if (do_dut_shutdown) dut_shutdown();
endtask

// dut shutdown - this is called in post_start if do_dut_shutdown bit is set
task dut_shutdown();
  csr_utils_pkg::wait_no_outstanding_access();
endtask

// 'body()' task of the base sequence implements logic to make the base virtual sequence reset safe.
//
// Process threading model is used to ensure resets are handled cleanly via fine grained process
// control and actual stimulus generation implemented in main_thread() are clean of reset management.
//
// Ideally body() does not need be rewritten for any reason and all sequence logic should only go
// into 'main_thread()' task
task dv_rand_rst_safe_base_vseq::body();
  process             reset_thread_id;
  process             main_thread_id ;

  `uvm_info (get_name(), "dv_rand_rst_safe_base_vseq::body() - Starting", UVM_LOW)
  test_params = dv_test_seq_params::type_id::create("test_seq_parameters");
  assert (test_params.randomize())
  else begin
    `uvm_fatal (get_name(), "DV Test Parameters Randomisation Failed")
  end

  // TODO: Have a discussion on how parameters can be organised
  // Turn off randomisation for test parameters once randomization is sucessful.
  // These parameters need to be stable for the rest of the test sequence execution
  test_params.constraint_mode(0);


  // 'monitor_reset()' task helps the sequence syncronise with 'reset' trigger. Synchronisation is
  // done only when reset is observed at the signal level.
  //
  // Actions taken when reset is triggered are different to when sequence actually triggers a reset,
  // since both threads run independantly.
  monitor_reset();

  // This is the start of the primary loop of the sequence. If reset testing is enabled, we will
  // have multiple passes through the loop, else a single pass is sufficient.
  while (test_params.num_reset_loops > 0) begin
    reset_thread_id = null;
    main_thread_id  = null;

    // Reduce the count of primary loop as we go through the loops
    test_params.num_reset_loops -= 1;

    `uvm_info (get_name(), $sformatf("test_params.num_reset_loops:%d",
                                     test_params.num_reset_loops), UVM_LOW)

    // Wait until reset has been released. The parent class is
    wait (in_reset == 0);
    if (test_params.do_dut_init) dut_init();

    // At this point the design should be out of reset and should be ready to
    // accept any programming command.
    //
    // Two threads are now spawned to perform stimulus generation for the DUT
    // 1 - Reset Thread
    // 2 - Main Thread
    //
    // These are concurrent threads as we would like to perform a reset at a
    // random time when the DUT is operational. If reset testing is enabled
    // the reset thread should complete before the main thread else it is a
    // testbench error. Toplevel constraints part of dv_test_seq_params is used
    // control the timing of the reset thread.
    //
    // The reset thread encapsulates the the reset sequence that is customised
    // to run the clock reset sequencer and the main thread is used for
    // functional stimulus generation

    // Spawn dynamic threads for reset and main
    // capture the process ids for fine grained process control
    fork
      begin : forked_reset_thread
        // Capture Process handle for the spawned process
        reset_thread_id = process::self();

        // Do Reset Testing if reset testing is enabled & there are more than 1
        // primary loops of the test looking to be executed.
        if (   test_params.num_reset_loops != 0
            && test_params.reset_testing == dv_test_seq_params::ENABLE) begin
          reset_trigger_thread (test_params);

          // At this point the feedback from 'monitor_reset()' is confirmed 'reset' is asserted.
          // Once confirmed, the 'forked_reset_thread' is complete and can finish
          wait (in_reset == 1);
        end
      end
      begin : forked_main_thread
        // Capture Process handle for the spawned process
        main_thread_id = process::self();
        main_thread (test_params);
      end
    join_none

    // Wait until both threads have spawned properly
    wait (reset_thread_id != null && main_thread_id  != null);

    // Now wait till 'forked_reset_thread' finishes.
    // Reset thread should always finish first
    reset_thread_id.await();

    // At this point we have one of the threads completed
    // If we are not in the final/only loop, and reset testing is enabled
    // We should now be able to conditionally kill main thread only as it should be operational.
    // if that is not the case, re-adjust reset timing on the 'reset_seq' to ensure reset is
      // triggered when 'main_thread' is operational.
    if (   test_params.num_reset_loops != 0
        && test_params.reset_testing == dv_test_seq_params::ENABLE) begin
      // If reset testing is enabled, the DUT should be in reset at this point.
      // So it is safe to terminate main thread and and return the sequencers to
      // idle state.

      `uvm_info (get_name(), "dv_rand_rst_safe_base_vseq::body() - Process Termination block",
                 UVM_LOW)
      if (   main_thread_id.status() == process::RUNNING
          || main_thread_id.status() == process::WAITING
          || main_thread_id.status() == process::SUSPENDED) begin
        `uvm_info (get_name(), "dv_rand_rst_safe_base_vseq::body() - killing main_thread()", UVM_LOW)
        main_thread_id.kill();
      end
      else if (main_thread_id.status() == process::FINISHED)  begin
          // If you ever encounter this error. Ensure the timing of the reset thread
          // is controlled to ensure it always terminates earlier than the main thread
          `uvm_warning (get_name(), {"Reset Testing Enabled and main_thread() finished before",
                                     " reset_trigger_thread()"})
      end
    end // if (test_params.reset_testing == ENABLE)
    else begin
        // If reset testing is not enabled/or in the final pass of the loop wait until the main
        // thread is completed
        `uvm_info (get_name(), "Waiting for main_thread() to complete", UVM_LOW)
        main_thread_id.await();
    end //else
  end // test_params.num_reset_loops > 0

  `uvm_info (get_name(), "dv_rand_rst_safe_base_vseq::body() - Exiting", UVM_LOW)

endtask : body


task dv_rand_rst_safe_base_vseq::reset_trigger_thread(const ref dv_test_seq_params  test_params);
  `uvm_fatal (get_name(), "Derived sequence needs to provide an implementation")

  // Any TB that implements the reset safety will need the below lines implemented in the derived
  // sequence. DV Lib does not have access to reset_seq at compile and hence the example is provided
  // such that derived TB base_vseq can implement

  // Uncomment the following lines in the derived TB base vseq
  // --- Start
  // reset_seq  rst_seq;

  // // Execute the reset sequence on the clk reset sequencer
  // rst_seq = reset_seq::type_id::create("reset_sequence");
  // rst_seq.start(p_sequencer.clk_rst_sequencer);
  // --- End

  // IF the TB has access to multiple reset domains it would be worth documenting how each of them
  // will respond to the primary reset triggered here.

endtask : reset_trigger_thread


task dv_rand_rst_safe_base_vseq::main_thread(const ref dv_test_seq_params  test_params);
  // This is the task for main execution focus of the virtual sequence i.e. the transaction
  // generator.
  // In this thread other interface specific sequences can be triggered and controlled.
  `uvm_fatal (get_name(), "Derived sequence needs to provide an implementation")
endtask : main_thread


task dv_rand_rst_safe_base_vseq::monitor_reset();
  // This task is primarily the feedback to the vseq when reset is triggered during normal operation
  // of the vseq.The vseq then takes actions via the 'handle_resest_assertion()'

  // The first reset is POR. Wait until a full reset cycle is observed
  cfg.reset_domain.wait_reset_assert();
  cfg.reset_domain.wait_reset_deassert();

  fork
    begin : reset_monitor_thread
      forever begin
        cfg.reset_domain.wait_reset_assert();
        `uvm_info(`gfn, "Reset Assertion - Stopping Sequences", UVM_LOW)

        in_reset = 1;
        handle_reset_assertion();

        cfg.reset_domain.wait_reset_deassert();
        in_reset = 0;
      end // forever
    end
  join_none
endtask


function void dv_rand_rst_safe_base_vseq::handle_reset_assertion ();
  // This function is to make sure all state elements in the sequence and env are brought to the
  // default state as what would be when the sequence was initially started.
  p_sequencer.handle_reset_assertion();
endfunction : handle_reset_assertion
