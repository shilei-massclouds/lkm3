// SPDX-License-Identifier: GPL-2.0-only

#![no_std]

use core::ffi::{c_char, c_int, c_void};

// Matches struct earlycon_id in include/linux/serial_core.h (Linux 6.12).
#[repr(C)]
pub struct EarlyconId {
    name: [u8; 15],
    name_term: u8,
    compatible: [u8; 128],
    setup: extern "C" fn(*mut c_void, *const c_char) -> c_int,
}

impl EarlyconId {
    pub const fn new(
        name: [u8; 15],
        compatible: [u8; 128],
        setup: extern "C" fn(*mut c_void, *const c_char) -> c_int,
    ) -> Self {
        Self {
            name,
            name_term: 0,
            compatible,
            setup,
        }
    }
}

const _: () = assert!(core::mem::offset_of!(EarlyconId, setup) == 144);
