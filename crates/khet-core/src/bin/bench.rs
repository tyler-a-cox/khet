//! Engine benchmark, mirroring `khet/engine/benchmark.py`.
//!
//! ```text
//! cargo run --release --bin bench
//! cargo run --release --bin bench -- --json results.json
//! ```
//!
//! Two workloads:
//!
//! **perft** - move generation plus make/unmake, no search logic and no
//! evaluation.  The number to watch when optimising the board itself.
//!
//! **search** - full alpha-beta to a fixed depth.  Includes evaluation,
//! ordering and the transposition table.
//!
//! Absolute timings drift with machine load, so run this and the Python
//! benchmark in the same sitting and treat the ratio as the result.  Unlike
//! PyPy there is no JIT to warm, but a short warmup pass is still run so the
//! caches and branch predictors are in the same state the Python numbers are
//! measured in.

use std::env;
use std::fmt::Write as _;
use std::time::Instant;

use khet_core::board::move_name;
use khet_core::{perft, GameBoard, Searcher};

struct Args {
    perft_depth: u32,
    search_depth: i32,
    json: Option<String>,
    only: Vec<String>,
    warmup: bool,
}

fn parse_args() -> Args {
    let mut args = Args {
        perft_depth: 4,
        search_depth: 6,
        json: None,
        only: vec!["perft".into(), "search".into()],
        warmup: true,
    };
    let argv: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < argv.len() {
        match argv[i].as_str() {
            "--perft-depth" => {
                i += 1;
                args.perft_depth = argv[i].parse().expect("--perft-depth wants an integer");
            }
            "--search-depth" => {
                i += 1;
                args.search_depth = argv[i].parse().expect("--search-depth wants an integer");
            }
            "--json" => {
                i += 1;
                args.json = Some(argv[i].clone());
            }
            "--only" => {
                i += 1;
                args.only = argv[i].split(',').map(|s| s.trim().to_string()).collect();
            }
            "--no-warmup" => args.warmup = false,
            "-h" | "--help" => {
                println!(
                    "usage: bench [--perft-depth N] [--search-depth N] \
                     [--only perft,search] [--json PATH] [--no-warmup]"
                );
                std::process::exit(0);
            }
            other => panic!("unknown argument: {}", other),
        }
        i += 1;
    }
    args
}

fn describe_runtime() -> String {
    format!(
        "Rust ({} profile) on {} {}",
        if cfg!(debug_assertions) { "debug" } else { "release" },
        env::consts::OS,
        env::consts::ARCH,
    )
}

struct PerftRow {
    depth: u32,
    nodes: u64,
    seconds: f64,
}

struct SearchRow {
    depth: i32,
    nodes: u64,
    seconds: f64,
    score: i32,
    best: String,
}

fn run_perft(max_depth: u32, warmup: bool) -> Vec<PerftRow> {
    println!("perft (move generation + make/unmake)");
    let mut rows = Vec::new();
    for depth in 1..=max_depth {
        if warmup && depth < max_depth {
            let mut board = GameBoard::default();
            perft(&mut board, depth);
        }
        let mut board = GameBoard::default();
        let start = Instant::now();
        let nodes = perft(&mut board, depth);
        let seconds = start.elapsed().as_secs_f64();
        let rate = if seconds > 0.0 {
            nodes as f64 / seconds
        } else {
            0.0
        };
        println!(
            "  depth {}: {:>12}  {:>8.3}s  {:>14} nodes/s",
            depth,
            thousands(nodes),
            seconds,
            thousands(rate as u64),
        );
        rows.push(PerftRow {
            depth,
            nodes,
            seconds,
        });
    }
    rows
}

fn run_search(max_depth: i32, warmup: bool) -> Vec<SearchRow> {
    println!("\nalpha-beta search");
    if warmup {
        let mut board = GameBoard::default();
        Searcher::basic().search(&mut board, 3, None);
    }
    let mut rows = Vec::new();
    for depth in 1..=max_depth {
        let mut board = GameBoard::default();
        // A fresh searcher per depth, exactly as the Python benchmark does, so
        // neither run gets to reuse a warm transposition table.
        let result = Searcher::basic().search(&mut board, depth, None);
        let best = result.mv.map(move_name).unwrap_or_else(|| "-".to_string());
        println!(
            "  depth {}: {:>12}  {:>8.3}s  {:>14} nodes/s  score {:>7}  best {}",
            depth,
            thousands(result.nodes),
            result.elapsed,
            thousands(result.nodes_per_second() as u64),
            result.score,
            best,
        );
        rows.push(SearchRow {
            depth,
            nodes: result.nodes,
            seconds: result.elapsed,
            score: result.score,
            best,
        });
        if result.elapsed > 30.0 {
            println!("  (stopping: over 30s)");
            break;
        }
    }
    rows
}

fn thousands(n: u64) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    out
}

fn main() {
    let args = parse_args();
    println!("{}", describe_runtime());
    if cfg!(debug_assertions) {
        // Debug Rust is roughly an order of magnitude slower than release and
        // would make the whole comparison meaningless.  Say so loudly rather
        // than let a bad number get written down.
        println!(
            "\n!! DEBUG BUILD - these timings mean nothing.\n\
             !! Re-run with: cargo run --release --bin bench\n"
        );
    }
    println!("warmup: {}\n", if args.warmup { "on" } else { "OFF" });

    let perft_rows = if args.only.iter().any(|s| s == "perft") {
        run_perft(args.perft_depth, args.warmup)
    } else {
        Vec::new()
    };
    let search_rows = if args.only.iter().any(|s| s == "search") {
        run_search(args.search_depth, args.warmup)
    } else {
        Vec::new()
    };

    if let Some(path) = args.json {
        let mut out = String::new();
        out.push_str("{\n");
        let _ = write!(out, "  \"engine\": \"rust\",\n  \"runtime\": \"{}\",\n", describe_runtime());
        out.push_str("  \"perft\": [\n");
        for (i, row) in perft_rows.iter().enumerate() {
            let _ = write!(
                out,
                "    {{\"depth\": {}, \"nodes\": {}, \"seconds\": {:.6}}}{}\n",
                row.depth,
                row.nodes,
                row.seconds,
                if i + 1 == perft_rows.len() { "" } else { "," }
            );
        }
        out.push_str("  ],\n  \"search\": [\n");
        for (i, row) in search_rows.iter().enumerate() {
            let _ = write!(
                out,
                "    {{\"depth\": {}, \"nodes\": {}, \"seconds\": {:.6}, \
                 \"score\": {}, \"best\": \"{}\"}}{}\n",
                row.depth,
                row.nodes,
                row.seconds,
                row.score,
                row.best,
                if i + 1 == search_rows.len() { "" } else { "," }
            );
        }
        out.push_str("  ]\n}\n");
        std::fs::write(&path, out).expect("could not write JSON results");
        println!("\nwrote {}", path);
    }
}
