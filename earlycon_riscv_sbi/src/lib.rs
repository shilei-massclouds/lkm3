// SPDX-License-Identifier: GPL-2.0-only

#![no_std]

use core::ffi::{c_char, c_int, c_void};
use earlycon::EarlyconId;

const fn sbi_name() -> [u8; 15] {
    let mut name = [0; 15];
    name[0] = b's';
    name[1] = b'b';
    name[2] = b'i';
    name
}

// The linker script keeps this input section in .init.data.
#[used]
#[unsafe(link_section = "__earlycon_table")]
static SBI_EARLYCON_ID: EarlyconId = EarlyconId::new(sbi_name(), [0; 128], early_sbi_setup);

extern "C" fn early_sbi_setup(_device: *mut c_void, _options: *const c_char) -> c_int {
    // TODO: Select the DBCN or SBI v0.1 console write callback.
    -19 // -ENODEV: the empty shell must not register an unusable console.
}
