//! A legacy Alt+] key and an OSC reply both begin with ESC ]. Use the Escape
//! ambiguity window until a numeric selector and semicolon identify a reply.
//! Completed replies (including unsupported ones) still take the normal path.

use std::time::{Duration, Instant};

use crate::event::{Event, InternalEvent, KeyCode, KeyEvent, KeyModifiers};

use super::Parser;

const ESCAPE_TIMEOUT: Duration = Duration::from_millis(20);
// Match the foreground/background color query budget after the OSC header.
const OSC_REPLY_TIMEOUT: Duration = Duration::from_secs(2);

impl Parser {
    pub(super) fn buffer_external_input(&mut self, buffer: &[u8]) {
        if self.pending_escape_expired() && self.has_osc_selector() {
            // The terminal's reply budget elapsed. Start fresh with these bytes.
            self.resolve_pending_escape();
        }
        // As for a lone Escape, give a queued continuation of ESC ] a chance to
        // complete the sequence even if the reader was descheduled.
        self.advance(buffer, true);
        if self.pending_escape_expired() {
            self.resolve_pending_escape();
        }
    }

    pub(super) fn track_pending_escape(&mut self) {
        self.pending_escape_deadline = match self.buffer.as_slice() {
            b"\x1b" | b"\x1b]" => Some(Instant::now() + ESCAPE_TIMEOUT),
            [0x1b, b']', selector @ .., b';']
                if !selector.is_empty() && selector.iter().all(u8::is_ascii_digit) =>
            {
                Some(Instant::now() + OSC_REPLY_TIMEOUT)
            }
            [0x1b, b']', ..] => self.pending_escape_deadline,
            _ => None,
        };
    }

    pub(super) fn interrupt_pending_osc(&mut self, byte: u8) {
        if !self.buffer.starts_with(b"\x1b]") {
            return;
        }
        if matches!(byte, 0x03 | 0x04) {
            self.resolve_pending_escape();
            // An incomplete UTF-8 character must not consume Ctrl+C or Ctrl+D.
            self.buffer.clear();
        } else if self.buffer.ends_with(b"\x1b") && byte != b'\\' {
            // The trailing ESC starts the next key or paste sequence.
            self.buffer.pop();
            self.resolve_pending_escape();
            self.buffer.clear();
            self.buffer.push(0x1b);
        }
    }

    pub(super) fn pending_escape_expired(&self) -> bool {
        self.pending_escape_deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
    }

    fn has_osc_selector(&self) -> bool {
        let Some(suffix) = self.buffer.strip_prefix(b"\x1b]") else {
            return false;
        };
        suffix.first().is_some_and(u8::is_ascii_digit)
            && suffix.iter().find(|b| !b.is_ascii_digit()) == Some(&b';')
    }

    fn resolve_pending_escape(&mut self) {
        self.pending_escape_deadline = None;
        if self.has_osc_selector() {
            // Keep truncated terminal replies out of keyboard input.
            self.buffer.clear();
        } else if self.buffer == b"\x1b" {
            self.internal_events
                .push_back(InternalEvent::Event(Event::Key(KeyCode::Esc.into())));
            self.buffer.clear();
        } else {
            debug_assert!(self.buffer.starts_with(b"\x1b]"));
            self.internal_events
                .push_back(InternalEvent::Event(Event::Key(KeyEvent::new(
                    KeyCode::Char(']'),
                    KeyModifiers::ALT,
                ))));
            // Decode the suffix exactly as live input, retaining partial UTF-8.
            let pending = std::mem::take(&mut self.buffer);
            self.advance(&pending[2..], false);
        }
    }

    pub(super) fn finish_pending_escape(&mut self) -> Option<InternalEvent> {
        if self.pending_escape_expired() {
            self.resolve_pending_escape();
        }
        self.next()
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use crate::event::{source::EventSource, sys::unix::parse::parse_event};

    use super::*;

    fn key(c: char, modifiers: KeyModifiers) -> InternalEvent {
        InternalEvent::Event(Event::Key(KeyEvent::new(KeyCode::Char(c), modifiers)))
    }

    fn alt_bracket() -> InternalEvent {
        key(']', KeyModifiers::ALT)
    }

    fn check_every_split(input: &[u8], expected: &[InternalEvent]) {
        for split in 0..=input.len() {
            let mut parser = Parser::default();
            parser.buffer_external_input(&input[..split]);
            parser.buffer_external_input(&input[split..]);
            assert_eq!(parser.collect::<Vec<_>>(), expected, "split {split}");
        }
    }

    #[test]
    fn live_reader_delivers_alt_bracket_and_text_without_another_write() {
        for text in ["", "fast", "10é🦀"] {
            let (mut reader, mut writer) = super::super::tests::source_with_input();
            write!(writer, "\x1b]{text}").unwrap();
            assert_eq!(
                reader.try_read(Some(Duration::from_secs(1))).unwrap(),
                Some(alt_bracket())
            );
            for c in text.chars() {
                assert_eq!(
                    reader.try_read(Some(Duration::ZERO)).unwrap(),
                    Some(key(c, KeyModifiers::NONE))
                );
            }
            assert_eq!(reader.try_read(Some(Duration::ZERO)).unwrap(), None);
        }
    }

    #[test]
    fn alt_bracket_preserves_interrupts_without_waiting_for_a_timeout() {
        for (byte, c) in [(3, 'c'), (4, 'd')] {
            for text in ["", "fast"] {
                let mut input = format!("\x1b]{text}").into_bytes();
                input.push(byte);
                let mut expected = vec![alt_bracket()];
                expected.extend(text.chars().map(|c| key(c, KeyModifiers::NONE)));
                expected.push(key(c, KeyModifiers::CONTROL));
                check_every_split(&input, &expected);
            }
        }
        check_every_split(
            b"\x1b]\x1b[99;5u",
            &[alt_bracket(), key('c', KeyModifiers::CONTROL)],
        );
    }

    #[test]
    fn partial_utf8_after_alt_bracket_survives_timeout() {
        let mut parser = Parser::default();
        parser.buffer_external_input(b"\x1b]\xc3");
        *parser.pending_escape_deadline.as_mut().unwrap() = Instant::now();
        assert_eq!(parser.finish_pending_escape(), Some(alt_bracket()));
        parser.buffer_external_input(b"\xa9");
        assert_eq!(parser.collect::<Vec<_>>(), [key('é', KeyModifiers::NONE)]);
    }

    #[test]
    fn fragmented_color_replies_do_not_become_keys() {
        for reply in [
            b"\x1b]10;rgb:ff/00/00\x07".as_slice(),
            b"\x1b]11;rgb:ff/00/00\x1b\\",
        ] {
            let event = parse_event(reply, false).unwrap().unwrap();
            assert!(matches!(event, InternalEvent::OscColor { .. }));
            check_every_split(reply, &[event]);
        }
    }

    #[test]
    fn truncated_osc_drops_reply_bytes_and_preserves_fresh_input() {
        let mut parser = Parser::default();
        parser.buffer_external_input(b"\x1b]10;");
        let deadline = parser.pending_escape_deadline.unwrap();
        parser.buffer_external_input(b"rgb:ff/");
        assert_eq!(parser.pending_escape_deadline, Some(deadline));
        parser.pending_escape_deadline = Some(Instant::now());
        parser.buffer_external_input(b"x");
        assert_eq!(parser.collect::<Vec<_>>(), [key('x', KeyModifiers::NONE)]);
        check_every_split(
            b"\x1b]52;c;unfinished\x03",
            &[key('c', KeyModifiers::CONTROL)],
        );
    }

    #[cfg(feature = "bracketed-paste")]
    #[test]
    fn alt_bracket_preserves_the_next_bracketed_paste() {
        check_every_split(
            b"\x1b]\x1b[200~literal\x1b]\x03\x1b[201~",
            &[
                alt_bracket(),
                InternalEvent::Event(Event::Paste("literal\x1b]\x03".into())),
            ],
        );
    }
}
