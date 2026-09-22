// SPDX-License-Identifier: GPL-2.0-only

#![no_std]

use core::ffi::{c_char, c_int, c_void};

earlycon::earlycon_declare!(sbi, early_sbi_setup);

extern "C" fn early_sbi_setup(_device: *mut c_void, _options: *const c_char) -> c_int {
    // TODO: Select the DBCN or SBI v0.1 console write callback.
    -19 // -ENODEV: the empty shell must not register an unusable console.
}
