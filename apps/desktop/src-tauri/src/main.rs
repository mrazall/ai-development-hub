// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(feature = "app")]
fn main() {
    aihub_desktop_lib::run();
}

#[cfg(not(feature = "app"))]
fn main() {}
