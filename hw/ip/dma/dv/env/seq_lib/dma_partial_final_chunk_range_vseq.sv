// Copyright zeroRISC Inc.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Directed legacy-environment reproducer for a legal final partial chunk at
// the upper boundary of the DMA-enabled OT-internal memory range.
//
// The 532-byte transfer consists of three complete 176-byte chunks and one
// final four-byte chunk. Fixed-address mode gives the source and destination
// agents FIFO semantics within each chunk. With chunk wrapping disabled, RTL
// advances the address CSRs by CHUNK_DATA_SIZE after each complete chunk, so
// the final destination chunk starts at 0x1210 and ends at 0x1213, one byte
// below the inclusive range limit 0x1214. The spare byte also satisfies the
// legacy constraint model's off-by-one range requirement. The DMA must
// validate the four bytes that remain, rather than requiring room for another
// complete 176-byte chunk.
//
// Keep this sequence on the legacy dma_generic_vseq path so it can serve as a
// small, directly upstreamable reproducer independent of reset-safe DV code.
class dma_partial_final_chunk_range_vseq extends dma_generic_vseq;
  `uvm_object_utils(dma_partial_final_chunk_range_vseq)
  `uvm_object_new

  constraint iters_c {num_iters == 1;}
  constraint transactions_c {num_txns == 1;}

  // The reproducer is a legal configuration whose expected outcome is a
  // successful transfer.
  virtual function bit pick_if_config_valid();
    return 1'b1;
  endfunction

  // Polling keeps the testcase independent of interrupt timing and limits it
  // to the enabled-memory range behavior under test.
  virtual function bit pick_if_intr_driven();
    return 1'b0;
  endfunction

  virtual function void randomize_item(ref dma_seq_item dma_config);
    dma_config.valid_dma_config  = 1'b1;
    dma_config.src_addr_in_range = 1'b1;
    dma_config.dst_addr_in_range = 1'b1;

    `DV_CHECK_RANDOMIZE_WITH_FATAL(
      dma_config,
      opcode == OpcCopy;
      handshake == 1'b0;
      per_transfer_width == DmaXfer1BperTxn;
      src_asid == SocControlAddr;
      dst_asid == OtInternalAddr;
      src_addr == 64'h0000_0000_0000_2000;
      dst_addr == 64'h0000_0000_0000_1000;
      // This is the configuration that exposes the defect. In fixed-address
      // mode each agent supplies FIFO behavior within a chunk, while no-wrap
      // mode advances the address CSRs by the programmed size between chunks.
      src_addr_inc == 1'b0;
      dst_addr_inc == 1'b0;
      src_chunk_wrap == 1'b0;
      dst_chunk_wrap == 1'b0;
      mem_range_valid == 1'b1;
      range_regwen == MuBi4True;
      mem_range_base == 32'h0000_1000;
      // The architectural final byte is 0x1213. Use one additional valid byte
      // so this directed RTL reproducer can coexist with the legacy sequence
      // item's conservative range constraint on upstream main.
      mem_range_limit == 32'h0000_1214;
      total_data_size == 532;
      chunk_data_size == 176;
      clear_intr_src == '0;)

    `DV_CHECK(dma_config.is_valid_config,
              "Directed final-partial-chunk configuration must be valid")
    `uvm_info(`gfn, $sformatf("DMA: Directed final-partial-chunk configuration:%s",
                              dma_config.convert2string()), UVM_MEDIUM)
  endfunction : randomize_item

  virtual task body();
    `uvm_info(`gfn, "DMA: Starting directed final-partial-chunk range reproducer", UVM_LOW)
    super.body();
    `uvm_info(`gfn, "DMA: Completed directed final-partial-chunk range reproducer", UVM_LOW)
  endtask : body
endclass : dma_partial_final_chunk_range_vseq
