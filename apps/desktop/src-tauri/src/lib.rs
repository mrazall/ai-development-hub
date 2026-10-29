pub mod secrets;
pub mod types;
pub mod url;
pub mod wsl;

#[cfg(feature = "app")]
mod app;
#[cfg(feature = "app")]
mod client;
#[cfg(feature = "app")]
mod commands;

#[cfg(feature = "app")]
pub fn run() {
    app::run();
}
