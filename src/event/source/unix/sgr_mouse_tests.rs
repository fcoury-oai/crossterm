use super::Parser;
use crate::event::{Event, InternalEvent, KeyCode};

#[test]
fn nan_mouse_reports_leave_the_next_key_at_every_split() {
    for report in [
        "\x1b[<16;NaN;NaNm",
        "\x1b[<0;NaN;NaNm",
        "\x1b[<64;NaN;12M",
        "\x1b[<0;32;NaNm",
    ] {
        let input = format!("{report}x");
        for split in 0..=input.len() {
            let mut parser = Parser::default();
            parser.buffer_external_input(&input.as_bytes()[..split]);
            parser.advance(&input.as_bytes()[split..], false);
            assert_eq!(
                parser.collect::<Vec<_>>(),
                [InternalEvent::Event(Event::Key(KeyCode::Char('x').into()))],
                "{report:?} split at {split}"
            );
        }
    }
}

#[test]
fn discarded_nan_mouse_report_does_not_leak_its_delayed_suffix() {
    let report = b"\x1b[<16;NaN;NaNm";
    for split in 1..report.len() {
        let mut parser = Parser::default();
        parser.advance(&report[..split], true);
        parser.discard_buffered_input();
        for byte in &report[split..] {
            parser.advance(std::slice::from_ref(byte), false);
        }
        parser.advance(b"x", false);
        assert_eq!(
            parser.collect::<Vec<_>>(),
            [InternalEvent::Event(Event::Key(KeyCode::Char('x').into()))],
            "split at {split}"
        );
    }
}

#[test]
fn interrupted_nan_mouse_report_reprocesses_the_next_byte() {
    for prefix in [
        "\x1b[<16;N",
        "\x1b[<0;Na",
        "\x1b[<0;NaN;NaN",
        "\x1b[<0;NaN;12345",
    ] {
        let mut parser = Parser::default();
        parser.advance(prefix.as_bytes(), false);
        parser.advance(b"x", false);
        assert_eq!(
            parser.collect::<Vec<_>>(),
            [InternalEvent::Event(Event::Key(KeyCode::Char('x').into()))],
            "{prefix:?}"
        );
    }
}

#[test]
fn truncated_nan_mouse_report_preserves_a_fresh_escape_sequence() {
    let mut parser = Parser::default();
    parser.advance(b"\x1b[<16;NaN;Na\x1b[A", false);
    assert_eq!(
        parser.collect::<Vec<_>>(),
        [InternalEvent::Event(Event::Key(KeyCode::Up.into()))]
    );
}

#[cfg(feature = "bracketed-paste")]
#[test]
fn nan_mouse_report_inside_paste_remains_literal() {
    let mut parser = Parser::default();
    parser.advance(b"\x1b[200~\x1b[<16;NaN;NaNm\x1b[201~", false);
    assert_eq!(
        parser.collect::<Vec<_>>(),
        [InternalEvent::Event(Event::Paste(
            "\x1b[<16;NaN;NaNm".into()
        ))]
    );
}
