// Copyright zeroRISC Inc.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Directed legacy-environment reproducer for SHA recovery after a DMA source
// response error. Both operations execute in one iteration, so no DUT reset
// can clean the private SHA state between them.
class dma_sha_error_recovery_vseq extends dma_generic_vseq;
  `uvm_object_utils(dma_sha_error_recovery_vseq)
  `uvm_object_new

  constraint iters_c {num_iters == 1;}
  constraint transactions_c {num_txns == 2;}

  virtual function bit pick_if_config_valid();
    return 1'b1;
  endfunction

  // Polling leaves a clear status-poll signature when the second operation
  // cannot start, without making the reproducer depend on interrupt timing.
  virtual function bit pick_if_intr_driven();
    return 1'b0;
  endfunction

  virtual function void randomize_item(ref dma_seq_item dma_config);
    dma_config.valid_dma_config  = 1'b1;
    dma_config.src_addr_in_range = 1'b1;
    dma_config.dst_addr_in_range = 1'b1;

    `DV_CHECK_RANDOMIZE_WITH_FATAL(
      dma_config,
      opcode == OpcSha256;
      handshake == 1'b0;
      per_transfer_width == DmaXfer4BperTxn;
      src_asid == SocControlAddr;
      dst_asid == OtInternalAddr;
      src_addr == 64'h0000_0000_0000_2000;
      dst_addr == 64'h0000_0000_0000_1000;
      src_addr_inc == 1'b1;
      dst_addr_inc == 1'b1;
      src_chunk_wrap == 1'b0;
      dst_chunk_wrap == 1'b0;
      mem_range_valid == 1'b1;
      range_regwen == MuBi4True;
      mem_range_base == 32'h0000_1000;
      mem_range_limit == 32'h0000_2000;
      total_data_size == 64;
      chunk_data_size == 64;
      clear_intr_src == '0;)

    `DV_CHECK(dma_config.is_valid_config,
              "Directed SHA error-recovery configuration must be valid")
  endfunction : randomize_item

  virtual task starting_txn(int unsigned txn, int unsigned num_txns,
                            ref dma_seq_item dma_config);
    super.starting_txn(txn, num_txns, dma_config);
    `DV_CHECK_EQ(num_txns, 2, "SHA error-recovery reproducer requires exactly two operations")

    // SHA reads source data but does not issue destination payload writes. The
    // legacy responder-wide error control therefore deterministically injects
    // a source response error into operation zero. Disable it before operation
    // one starts so that recovery is tested with an otherwise clean transfer.
    enable_bus_errors(txn == 0 ? 100 : 0);
    `uvm_info(`gfn, $sformatf("SHA recovery operation %0d: source response error %s",
                              txn, txn == 0 ? "enabled" : "disabled"), UVM_LOW)
  endtask : starting_txn

  virtual task ending_txn(int unsigned txn, int unsigned num_txns,
                          ref dma_seq_item dma_config, status_t status);
    super.ending_txn(txn, num_txns, dma_config, status);
    `DV_CHECK_EQ(status[StatusError], txn == 0,
                 "Only the first SHA operation must report the injected response error")
    `DV_CHECK_EQ(status[StatusDone], txn == 1,
                 "The second SHA operation must recover and complete")
    `DV_CHECK_EQ(status[StatusAborted], 1'b0,
                 "SHA recovery reproducer must not abort either operation")
    `DV_CHECK_EQ(status[StatusChunkDone], 1'b0,
                 "Each SHA operation contains a single complete chunk")
  endtask : ending_txn

  virtual task body();
    `uvm_info(`gfn, "DMA: Starting directed legacy SHA error-recovery reproducer", UVM_LOW)
    super.body();
    `uvm_info(`gfn, "DMA: Completed directed legacy SHA error-recovery reproducer", UVM_LOW)
  endtask : body
endclass : dma_sha_error_recovery_vseq
