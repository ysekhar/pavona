// Copyright zeroRISC Inc
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

class dv_test_seq_params extends uvm_sequence_item;
  typedef enum {DISABLE=0, ENABLE} ENABLE_TYPE;

  rand ENABLE_TYPE      reset_testing  ;
  rand int              num_reset_loops;

  rand uint             num_trans;

  // Controls for DUT initialization and Shutdown
  bit do_dut_init       = 1'b1;
  bit do_dut_shutdown   = 1'b1;

  `uvm_object_utils_begin (dv_test_seq_params)
      `uvm_field_enum (ENABLE_TYPE, reset_testing  , UVM_ALL_ON          )
      `uvm_field_int  (             num_reset_loops, UVM_ALL_ON | UVM_DEC)
  `uvm_object_utils_end

  function new(string name = "");
  endfunction : new

  constraint num_trans_c {
    num_trans inside {[1:20]};
  }

  constraint reset_loops {
      if (reset_testing == ENABLE) num_reset_loops inside {[2:5]};
      else num_reset_loops == 1;
  }

  constraint additional {
      // Constraints for Test that are to be spcified in the
      // derived class
  }
endclass : dv_test_seq_params
