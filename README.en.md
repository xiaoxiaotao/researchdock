# ResearchDock · 研迹

A local-first financial research knowledge base: archive source documents, follow industries and companies, trace research changes, and use AI only where it adds value.

[详细中文文档](README.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [MIT](LICENSE)

## Features

- Versioned Markdown archives, source attachments, full-text search, reading state and saved views.
- Optional authorized ZSXQ CLI ingestion and public Youdao note extraction.
- A-share / Hong Kong security-name matching; A-share financial statements via public APIs.
- Company source timelines, evidence clips, research notes and questions.
- Optional DeepSeek classification, manual in-depth assessment and user-triggered bilingual report translation.
- Per-document and historical-version PDF export, generated locally without AI.
- Economy mode enabled by default; successful model calls cached with durable receipts and request limits.

## Start

Python 3.13; macOS is the primary tested platform. Ubuntu CI is included, but its remote result is available only after the repository is pushed. Native Windows is not yet validated.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.yaml config.yaml
bash run.sh
```

Open http://127.0.0.1:8001. No frontend build or Codex installation is required. Data starts empty; optional synthetic samples: `python -m app.seed`.

No API key is required for local import and reading. Configure DeepSeek through the system keyring or `DEEPSEEK_API_KEY` in the process environment. Enabled AI tasks transmit the relevant text to DeepSeek and may incur charges. ZSXQ requires your own official CLI installation, authorization and access rights.

## Boundaries

Local single-user software, not a public web service or a trading/valuation system. Keep the loopback binding. Hong Kong financial statements, OCR and audio transcription are not implemented. Overseas institution entries are a mix of public indexes, limited official PDF links and user-supplied imports, not unrestricted paid research APIs. Public access does not grant redistribution rights.

## Development / source release

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
python -m app.verify
python scripts/build_release.py --check
python scripts/build_release.py
```

Upload only the reviewed `dist/researchdock/` source tree or generated ZIP. Private data, credentials, source research PDFs, screenshots, virtual environments and original Git history are excluded. See the Chinese README for detailed setup, architecture, source integrations, data formats, backups and publishing steps.
