// SPDX-License-Identifier: GPL-2.0-only

use super::*;

extern "C" fn setup(_device: *mut c_void, _options: *const c_char) -> c_int {
    0
}

earlycon_declare!(first, setup);
earlycon_declare!(second, setup);

#[test]
fn name_is_zero_padded() {
    let id = EarlyconId::new("sbi", [0; 128], setup);
    assert_eq!(&id.name[..4], b"sbi\0");
    assert_eq!(id.name_term, 0);
}
