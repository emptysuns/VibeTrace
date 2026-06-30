# VibeTrace Desktop

> AI Agent observability, debugging & reliability - in a desktop app.
>
> Calm, insightful, minimalist. Built with Tauri + Rust + React.

[![Build](https://github.com/sakurairo/VibeTrace/actions/workflows/release.yml/badge.svg)](https://github.com/sakurairo/VibeTrace/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is VibeTrace?

VibeTrace is a desktop application that **automatically captures, visualizes, and analyzes** every step of an AI agent's execution, with a special focus on **vibe deviation**: detecting when the actual behavior drifts from the intended vibe/style.

It works out-of-the-box with **Claude Code** (via the official hooks protocol), and can be extended to any AI agent.

## Features

- **One-click Claude Code integration** - auto-configures `~/.claude/settings.json`
- **Visual timeline + graph** - see every LLM call, tool use, and reasoning step
- **AI-powered Analyst** - root cause analysis, cost hotspots, loop detection
- **Vibe Check** - detect when output deviates from intended style (calm, minimalist, professional, etc.)
- **Loop detection** - get warned when the same reasoning repeats
- **Local-first** - all data stays on your machine (SQLite), no cloud dependency
- **Native performance** - Tauri + Rust + React
- **Dark theme** - designed for long debugging sessions

## Installation

Download the latest release for your platform from [GitHub Releases](https://github.com/sakurairo/VibeTrace/releases):

- **macOS**: `.dmg` or `.app`
- **Windows**: `.msi` or `.exe`
- **Linux**: `.deb`, `.rpm`, or `.AppImage`

## Quick Start

1. **Launch VibeTrace** - the app auto-starts a local HTTP server on `http://127.0.0.1:7842`
2. **Click "Setup Claude Code Hooks"** in the sidebar
3. **Use Claude Code normally** - every prompt, tool call, and reasoning step is captured
4. **Open the desktop app** to see live traces, analyze patterns, check vibe deviation

## Architecture

```
┌─────────────────┐     HTTP POST      ┌──────────────────┐
│  Claude Code    │ ─────────────────► │  VibeTrace       │
│  (via hooks)    │   /v1/traces       │  HTTP server     │
└─────────────────┘   /v1/events       │  (Rust/axum)     │
                                       └────────┬─────────┘
                                                │
                                       ┌────────▼─────────┐
                                       │  SQLite (rusqlite)│
                                       └────────┬─────────┘
                                                │
                                       ┌────────▼─────────┐
                                       │  React Frontend  │
                                       │  (Tauri Webview) │
                                       └──────────────────┘
```

- **Backend**: Rust + Tauri + axum (HTTP) + rusqlite (SQLite)
- **Frontend**: React + TypeScript + Vite
- **Database**: bundled SQLite (zero-config, no external deps)

## Development

Prerequisites:
- [Rust](https://rustup.rs/) ≥ 1.75
- [Node.js](https://nodejs.org/) ≥ 18
- [Tauri CLI](https://tauri.app/start/prerequisites/): `cargo install tauri-cli`

```bash
npm install
npm run tauri dev
```

## Claude Code Integration

VibeTrace auto-configures three Claude Code hooks:

| Hook | Captures |
|------|----------|
| `UserPromptSubmit` | Your prompt, starts new trace |
| `PostToolUse` | Tool calls (Bash, Read, Edit, etc.) |
| `Stop` | Marks trace as complete |

The hook configuration is written to `~/.claude/settings.json` and uses `curl` to call VibeTrace's local HTTP API.

## License

MIT © VibeTrace Contributors

---

*Built with vibe coding - calm, insightful, minimalist.*
