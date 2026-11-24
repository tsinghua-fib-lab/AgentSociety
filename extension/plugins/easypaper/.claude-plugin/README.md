# easypaper

AI-powered academic paper generation plugin for Claude Code.

## Description

Generate LaTeX academic papers from metadata interactively. The plugin provides a guided workflow to collect all necessary information and automatically sets up the required environment.

## Quick Start

After installing the plugin, simply run:

```
/easypaper
```

The plugin will:
1. **Automatically set up the environment** (first time only):
   - Create an isolated Python virtual environment
   - Install easypaper package and dependencies
   - Check and guide LaTeX installation

2. **Guide you through metadata collection**:
   - Check if you have complete metadata (file or JSON)
   - If not, collect all required fields interactively (title, hypothesis, method, data, experiments, references)
   - Ask about optional fields (venue, page count, review options, etc.)
   - Allow you to review and edit before generation

3. **Generate your paper**:
   - Use EasyPaper Python SDK directly (no API server needed)
   - Generate the paper from metadata
   - Provide output files (LaTeX source, references, PDF if compiled)

## Manual Setup (Optional)

If you prefer to set up manually or need to troubleshoot:

```bash
# Set up environment
/easypaper-setup

# Or manually:
# Using uv (recommended)
uv venv .easypaper-env
source .easypaper-env/bin/activate
uv pip install easypaper

# Using standard Python
python -m venv .easypaper-env
source .easypaper-env/bin/activate
pip install easypaper
```

## Prerequisites

- **Python 3.11+** (automatically checked)
- **LaTeX toolchain** (automatically checked, installation instructions provided if missing)
  - macOS: `brew install --cask mactex` or `brew install basictex`
  - Linux: `sudo apt-get install texlive-full`
  - Windows: Install MiKTeX or TeX Live
- **API key for LLM provider** (configured via config file)

## Configuration

If you do not already have a config, run `/easypaper-setup`. The setup skill
creates `easypaper_config.yaml` from its bundled `config.example.yaml`, which is
kept synchronized with the current EasyPaper `configs/example.yaml` template.
You only need to replace the API key placeholders.

For reference, a minimal agent entry looks like:

```yaml
agents:
  - name: metadata
    model:
      model_name: claude-sonnet-4-20250514
      api_key: YOUR_API_KEY
      base_url: https://api.anthropic.com/v1
  # ... other agents
```

The config path will be requested when initializing EasyPaper.

## Metadata Structure

The plugin collects metadata following the structure in `examples/meta.json`:

**Required fields:**
- `title`: Paper title
- `idea_hypothesis`: Core research question or hypothesis
- `method`: Research methodology
- `data`: Data sources and collection process
- `experiments`: Experimental results and findings
- `references`: List of references (BibTeX or structured format)

**Optional fields:**
- `style_guide`: Venue name (NeurIPS, ICML, ICLR, ACL, AAAI, COLM, Nature)
- `target_pages`: Target page count (uses venue/default planning when omitted)
- `template_path`: Custom LaTeX template path
- `compile_pdf`: Whether to compile PDF (default: true)
- `enable_review`: Enable text review/revision loop (default: true)
- `enable_vlm_review`: Enable VLM/PDF visual review and page-overflow checks (default: false)
- `max_review_iterations`: Max review iterations (default: 3)
- `materials_root`: Base directory for relative figure/table asset paths
- `figures`: Array of figure objects
- `tables`: Array of table objects
- `code_repository`: Code repository configuration
- `output_dir`: Output directory path

Metadata files should use relative paths where practical. Figure/table assets
resolve through `materials_root` first and then the current working directory.
When loading metadata from a file, helper scripts set `materials_root` to the
metadata file parent if it is missing and normalize `template_path` plus local
`code_repository.path` before SDK execution.

## Supported Venues

- NeurIPS
- ICML
- ICLR
- ACL
- AAAI
- COLM
- Nature

## Commands

- `/easypaper` - Main command: guided workflow from setup to paper generation
- `/easypaper-setup` - Set up environment manually
- `/easypaper-paper-from-metadata` - Generate paper directly from existing metadata JSON
- `/easypaper-paper-section` - Generate or rewrite a single paper section
- `/easypaper-metadata-build` - Claude-driven interactive build of `PaperMetaData` from a research-materials folder (cold / warm-start / refine modes); complements the SDK one-shot `generate_metadata_from_folder`

## Manual Install (without Claude Code marketplace)

If you cloned this repo directly and want to install the skills and slash commands
without using the marketplace flow, two convenience scripts are provided. Both
scripts copy (or symlink) every skill under `plugins/easypaper/skills/` and every
slash command under `plugins/easypaper/commands/` into the chosen target.

### Targets

- `--global` / `-Global` → `$HOME/.claude/{skills,commands}/` (user-level, all projects)
- `--project` / `-Project` → `$(pwd)/.claude/{skills,commands}/` (current project only)
- `--project=<path>` / `-ProjectPath <path>` → `<path>/.claude/{skills,commands}/`

### Bash (macOS / Linux / Git Bash / WSL)

```bash
# Preview what would be installed (no target needed)
bash scripts/install_plugin.sh --list

# Install to user-level
bash scripts/install_plugin.sh --global

# Install to current project
bash scripts/install_plugin.sh --project

# Install to a specific project, using symlinks so future repo updates flow through
bash scripts/install_plugin.sh --project=/path/to/research --symlink

# See exactly what would happen, no writes
bash scripts/install_plugin.sh --global --dry-run

# Clean removal
bash scripts/install_plugin.sh --global --uninstall -y
```

### PowerShell (Windows)

```powershell
# Preview
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -List

# User-level install
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -Global

# Current project
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -Project

# Specific project with symlinks (requires Developer Mode or admin)
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -ProjectPath .\research -Symlink

# Dry-run
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -Global -DryRun

# Uninstall
powershell -ExecutionPolicy Bypass -File scripts\install_plugin.ps1 -Global -Uninstall -Yes
```

### Modes

- `--copy` / default (PowerShell: omit `-Symlink`) — copies files. Safest cross-platform.
- `--symlink` / `-Symlink` — creates symlinks so updates from this repo flow into your Claude Code install automatically. On Windows this requires Developer Mode or running PowerShell as Administrator.

After install, restart Claude Code (or rescan plugins) so the new skills and commands are picked up.
