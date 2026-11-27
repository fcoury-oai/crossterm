use crossterm::event::{Event, KeyCode, KeyEventKind};
use std::fs::File;
use std::io::{Result, Write};

fn main() -> Result<()> {
    crossterm::terminal::enable_raw_mode()?;
    let mut log = File::create(std::env::args_os().nth(1).unwrap())?;
    loop {
        if let Event::Key(k) = crossterm::event::read()? {
            if k.kind == KeyEventKind::Press {
                match k.code {
                    KeyCode::Char(c) => writeln!(log, "U+{:04X} {:02X}", c as u32, k.modifiers.bits())?,
                    KeyCode::End => writeln!(log, "END")?,
                    code => writeln!(log, "{code:?} {:02X}", k.modifiers.bits())?,
                }
            }
        }
    }
}
