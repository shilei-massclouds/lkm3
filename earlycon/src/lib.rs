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
        name: &str,
        compatible: [u8; 128],
        setup: extern "C" fn(*mut c_void, *const c_char) -> c_int,
    ) -> Self {
        let bytes = name.as_bytes();
        assert!(bytes.len() <= 15);

        let mut name = [0; 15];
        let (prefix, _) = name.split_at_mut(bytes.len());
        prefix.copy_from_slice(bytes);

        Self {
            name,
            name_term: 0,
            compatible,
            setup,
        }
    }
}

const _: () = assert!(core::mem::offset_of!(EarlyconId, setup) == 144);

/// Declares an early console entry with the same name and setup as EARLYCON_DECLARE.
#[macro_export]
macro_rules! earlycon_declare {
    ($name:ident, $setup:path) => {
        const _: () = {
            #[used]
            #[unsafe(link_section = "__earlycon_table")]
            static ID: $crate::EarlyconId =
                $crate::EarlyconId::new(stringify!($name), [0; 128], $setup);
        };
    };
}

#[cfg(test)]
mod tests;
