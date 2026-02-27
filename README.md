# 📚 Anki Deck Generator

Turn any PDF, DOCX, or TXT file into Anki flashcards — powered by AI (local or cloud) or simple offline heuristics.

> **TL;DR** — Point it at your textbook, get a study deck. Runs 100% locally with [Ollama](https://ollama.com), no API key needed.

---

## ✨ Features

- **Multi-format input** — PDF (with tables, images, figure captions), DOCX, TXT, Markdown
- **Three AI backends** — Local Ollama (free/private), Claude API (highest quality), or offline regex
- **Exact source text** — Card backs always preserve the original wording from your document
- **Smart card types** — Questions, cloze deletions (`_____`), and image-based cards
- **Figure/diagram extraction** — Extracts images from PDFs and links them to relevant cards using caption matching
- **Boilerplate filtering** — Automatically skips table of contents, acknowledgements, index, bibliography, etc.
- **Auto-tagging** — Cards tagged by topic (e.g. `networking::load-balancing`)
- **8GB Mac friendly** — Low-memory mode for M1/M2 Macs with 8GB RAM
- **Robust JSON parsing** — Handles malformed LLM output (newlines in strings, truncated responses, wrong key names)

---

## 🚀 Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/anki-deck-generator.git
cd anki-deck-generator
pip install -r requirements.txt
```

### 2. Install Ollama (for local AI — recommended)

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

Start the server and pull a model:

```bash
ollama serve          # keep running in a terminal
ollama pull phi3:mini # 1.6 GB — fast, good for 8GB Macs
```

### 3. (Optional) Install poppler for better image extraction

```bash
# macOS
brew install poppler

# Ubuntu/Debian
sudo apt install poppler-utils

# Windows — download from: https://github.com/oschwartz10612/poppler-windows/releases
```

Without poppler, the tool falls back to Python-based extraction which misses some images.

### 4. Generate your deck

```bash
python anki_generator.py textbook.pdf --ollama --model phi3:mini
```

That's it. You'll get a `.csv` file and a `_media/` folder with images.

---

## 📖 Usage

### Basic commands

```bash
# Local Ollama (recommended)
python anki_generator.py textbook.pdf --ollama

# Specific model
python anki_generator.py notes.docx --ollama --model mistral

# Claude API (needs ANTHROPIC_API_KEY env var)
python anki_generator.py textbook.pdf

# Offline (no AI, regex-based — instant but lower quality)
python anki_generator.py notes.txt --offline
```

### Controlling card count

```bash
# Target ~5 cards per page of content
python anki_generator.py textbook.pdf --ollama -cpp 5

# Target a specific total
python anki_generator.py textbook.pdf --ollama -m 100

# Dense: 10 cards per page
python anki_generator.py textbook.pdf --ollama -cpp 10
```

### Processing large PDFs (especially on 8GB Macs)

```bash
# Process pages 1-50 in low-memory mode
python anki_generator.py big_textbook.pdf --ollama --low-mem --model phi3:mini --pages 1-50

# Batch a 269-page book:
python anki_generator.py book.pdf --ollama --low-mem --model phi3:mini --pages 1-50 -o part1.csv
python anki_generator.py book.pdf --ollama --low-mem --model phi3:mini --pages 51-100 -o part2.csv
python anki_generator.py book.pdf --ollama --low-mem --model phi3:mini --pages 101-150 -o part3.csv
# ... and so on
```

### All options

```
python anki_generator.py <input_file> [options]

Positional:
  input_file                   PDF, DOCX, or TXT file

Backend (pick one):
  (default)                    Claude API (needs ANTHROPIC_API_KEY)
  --ollama                     Local Ollama LLM (free, private)
  --offline                    Rule-based heuristics (no AI)

Options:
  --output, -o FILE            Output CSV filename
  --deck, -d NAME              Anki deck name (default: from filename)
  --model MODEL                Ollama model (default: llama3.1:8b)
  --max-cards, -m N            Target total number of cards
  --cards-per-page, -cpp N     Target cards per page (e.g. 5)
  --pages, -p RANGE            Page range for PDFs (e.g. "1-50")
  --low-mem                    Low memory mode for 8GB Macs
  --anki-connect               Push cards directly to Anki via AnkiConnect
  --api-key KEY                Anthropic API key (or set ANTHROPIC_API_KEY)
  --verbose, -v                Show detailed progress
```

---

## 📥 Importing into Anki

### Step 1: Import the CSV

1. Open Anki → **File → Import**
2. Select the generated `.csv` file
3. Anki should auto-detect settings from the file header. Verify:
   - **Type**: Basic
   - **Separator**: Tab
   - **Allow HTML in fields**: Yes
   - **Field 1** → Front, **Field 2** → Back, **Field 3** → Tags
4. Click **Import**

### Step 2: Copy images (if your document had figures)

Images are saved to a `*_media/` folder next to the CSV. Copy them to Anki's media folder:

```bash
# macOS
cp *_media/* ~/Library/Application\ Support/Anki2/User\ 1/collection.media/

# Linux
cp *_media/* ~/.local/share/Anki2/User\ 1/collection.media/

# Windows
copy *_media\* %APPDATA%\Anki2\User 1\collection.media\
```

Replace `User 1` with your Anki profile name.

---

## 🧠 How It Works

```
  PDF / DOCX / TXT
        │
        ▼
  ┌─────────────────────────┐
  │  1. Extract text         │  Tables → formatted text
  │     + images             │  Images → via poppler/pdfplumber/pypdf
  │     + figure captions    │  Captions → "Figure 1-1: ..." parsed
  └─────────────────────────┘
        │
        ▼
  ┌─────────────────────────┐
  │  2. Filter boilerplate   │  Skips: TOC, acknowledgements, index,
  │                          │  bibliography, glossary, review questions...
  └─────────────────────────┘
        │
        ▼
  ┌─────────────────────────┐
  │  3. Generate cards       │  Ollama / Claude API / offline regex
  │     (chunked for large   │  JSON output with repair for LLM quirks
  │      documents)          │  Normalizes varying key names
  └─────────────────────────┘
        │
        ▼
  ┌─────────────────────────┐
  │  4. Attach images        │  Caption label match → page proximity
  │     to cards             │  → figure number fallback
  └─────────────────────────┘
        │
        ▼
  ┌─────────────────────────┐
  │  5. Export                │  CSV (tab-separated, HTML-enabled)
  │                          │  + media folder with images
  │                          │  + optional AnkiConnect push
  └─────────────────────────┘
```

### Content filtering

The tool automatically skips sections that aren't "study material":

> Table of Contents, Introduction, Preface, Foreword, Acknowledgements, Dedication, About the Author, Index, Bibliography, References, Glossary, Appendix, Review Questions, Answer Key, List of Figures/Tables, Copyright, ISBN...

Both `# Markdown headings` and `ALL CAPS HEADINGS` (common in PDFs) are detected.

### Image matching (3-tier strategy)

1. **Caption label** — Text says "Figure 1-2", we found a caption "Figure 1-2: Request flow" on a page → exact match to that page's image
2. **Page proximity** — Card's source text came from page 15, page 15 has an image → attach it
3. **Figure number as index** — Last resort fallback

### JSON repair

Local LLMs sometimes produce broken JSON. The parser auto-fixes:
- Newlines inside strings
- Trailing commas
- Truncated output (salvages complete cards)
- Varying key names (`question`/`answer` instead of `front`/`back`, etc.)

---

## 🤖 Model Recommendations

### For Ollama

| Model | Size | RAM needed | Speed | Quality | Best for |
|-------|------|-----------|-------|---------|----------|
| `phi3:mini` | 1.6 GB | 4 GB | ★★★★★ | ★★★ | 8GB Macs, quick runs |
| `mistral` | 4.1 GB | 6 GB | ★★★★ | ★★★★ | General use |
| `llama3.1:8b` | 4.7 GB | 8 GB | ★★★★ | ★★★★ | Default, reliable |
| `qwen2.5:7b` | 4.4 GB | 6 GB | ★★★★ | ★★★★★ | Best JSON structure |
| `gemma2:9b` | 5.4 GB | 8 GB | ★★★ | ★★★★★ | Dense/technical content |

**8GB Mac?** Use `phi3:mini` with `--low-mem`. Process large PDFs in 30-50 page batches with `--pages`.

**16GB+ Mac?** Any model works. Try `llama3.1:8b` or `qwen2.5:7b` for best results.

---

## 🃏 Card Examples

**Input** (from a biology textbook):

> "Mitochondria are membrane-bound organelles found in the cytoplasm of eukaryotic cells. They are often referred to as the 'powerhouse of the cell' because they generate most of the cell's supply of adenosine triphosphate (ATP)."

**Generated cards:**

| Type | Front | Back |
|------|-------|------|
| Question | What are mitochondria? | Mitochondria are membrane-bound organelles found in the cytoplasm of eukaryotic cells. |
| Cloze | Mitochondria are often referred to as the '`_____`' because they generate most of the cell's supply of ATP. | **powerhouse of the cell** — *[full source text]* |
| Question | What molecule do mitochondria primarily produce? | They generate most of the cell's supply of adenosine triphosphate (ATP). |

---

## 🔧 Troubleshooting

### Ollama crashes (HTTP 500 / out of memory)

```bash
# Use low-memory mode + smallest model + page range
python anki_generator.py big.pdf --ollama --low-mem --model phi3:mini --pages 1-30
```

### Only 1-2 cards generated

The model ran out of output tokens or the prompt was too generic. Fix:

```bash
# Set explicit card target
python anki_generator.py doc.pdf --ollama -m 50

# Or cards-per-page
python anki_generator.py doc.pdf --ollama -cpp 5
```

### Images not showing in Anki

1. Make sure you copied `*_media/*` files to Anki's `collection.media/` folder
2. Install `poppler` for reliable image extraction: `brew install poppler`
3. Re-run the generator after installing poppler

### JSON parse errors

The tool auto-repairs most LLM output issues. If it still fails, try a different model — `qwen2.5:7b` produces the cleanest JSON.

### "No text could be extracted"

The PDF might be scanned (image-only). OCR support isn't built in yet. Workaround: use an OCR tool first (like `ocrmypdf`) to make the PDF searchable, then run the generator.

---

## 📁 Project Structure

```
anki-deck-generator/
├── anki_generator.py    # Main script (single file, no other code deps)
├── requirements.txt     # Python dependencies
├── setup.py             # pip install support
├── README.md
├── LICENSE              # MIT
└── .gitignore
```

---

## 📄 License

MIT — use it however you want.
