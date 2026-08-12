use std::env;
use std::io::{self, BufRead, Write};

const READY_MARKER: &str = "RPS_READY_V1";
const GAMMA: u64 = 0x9e3779b97f4a7c15;

pub struct RpsRandom {
    state: u64,
}

impl RpsRandom {
    pub fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(GAMMA);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
        value ^ (value >> 31)
    }

    pub fn next_usize(&mut self, upper_exclusive: usize) -> usize {
        assert!(upper_exclusive > 0, "upper_exclusive must be positive");
        let bound = upper_exclusive as u64;
        let threshold = bound.wrapping_neg() % bound;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return (value % bound) as usize;
            }
        }
    }
}

include!("strategy.rs");

fn fail(message: &str) -> ! {
    eprintln!("Rust wrapper: {message}");
    std::process::exit(2);
}

fn history(value: &str) -> &str {
    if value == "-" { "" } else { value }
}

fn main() {
    if env::var("RPS_PROTOCOL_VERSION").as_deref() != Ok("1") {
        fail("unsupported RPS_PROTOCOL_VERSION");
    }
    let seed_value = env::var("RPS_SEED")
        .unwrap_or_else(|_| fail("RPS_SEED must be an unsigned 64-bit integer"));
    let seed = seed_value
        .parse::<u64>()
        .unwrap_or_else(|_| fail("RPS_SEED must be an unsigned 64-bit integer"));
    let rounds = env::var("RPS_ROUNDS").unwrap_or_default();
    for (name, _) in env::vars() {
        unsafe { env::remove_var(name) };
    }
    for (name, value) in [
        ("HOME", "/tmp"),
        ("LANG", "C.UTF-8"),
        ("LC_ALL", "C.UTF-8"),
        ("TZ", "UTC"),
        ("RPS_PROTOCOL_VERSION", "1"),
        ("RPS_ROUNDS", rounds.as_str()),
        ("RPS_SEED", seed_value.as_str()),
    ] {
        unsafe { env::set_var(name, value) };
    }

    let mut rng = RpsRandom::new(seed);
    eprintln!("{READY_MARKER}");
    io::stderr().flush().unwrap_or_else(|_| fail("readiness output failed"));
    let mut lines = io::stdin().lock().lines();
    let mut output = io::BufWriter::new(io::stdout().lock());
    while let Some(turn_value) = lines.next() {
        let turn_value = turn_value.unwrap_or_else(|_| fail("protocol input failed"));
        let my_history = match lines.next() {
            Some(Ok(value)) => value,
            Some(Err(_)) => fail("protocol input failed"),
            None => return,
        };
        let opponent_history = match lines.next() {
            Some(Ok(value)) => value,
            Some(Err(_)) => fail("protocol input failed"),
            None => return,
        };
        let turn = turn_value
            .trim()
            .parse::<usize>()
            .unwrap_or_else(|_| fail("Turn must be a non-negative integer"));
        writeln!(
            output,
            "{}",
            choose_move(turn, history(&my_history), history(&opponent_history), &mut rng)
        )
        .unwrap_or_else(|_| fail("protocol output failed"));
        output.flush().unwrap_or_else(|_| fail("protocol output failed"));
    }
}
