# TRC Manager

TRC Manager is a Streamlit application and modular processing pipeline for handling Transcribed Remote Calls ("TRCs") associated with incidents. It ingests `.vtt` transcript files named with an Incident identifier and timestamp, runs a configurable multi-stage NLP pipeline, and produces structured artifacts: cleaned/refined text, extracted people/roles/knowledge, per-call summaries, keywords, and an incident-level master summary.

## Key Features
- Upload multiple `.vtt` transcript files per incident.
- Automatic incident file management (`data/incidents/INC*.json`).
- Modular pipeline stages (vtt_cleanup, refinement, people_extraction, summarisation, keyword_extraction, master_summary).
- Stage dependency resolution and partial re-runs from any stage.
- Artifact persistence (text + JSON) under `data/artifacts/`.
- People directory aggregation with discovered roles & knowledge.
- Interactive editing of titles, summaries, people metadata, and configuration.

## Repository Layout
```
app.py                 # Streamlit UI entry point
trc/pipeline.py        # Core pipeline runner & helpers
trc/stages/            # Built-in stage implementations
config.json            # Current pipeline configuration (editable in UI)
README.md              # Project documentation
AGENTS.md              # Agent instructions for automated tooling
```
Dynamic / generated data (ignored by git) lives under `data/` (incidents, people, uploads, artifacts).

## Transcript Filename Convention
Uploaded `.vtt` files must embed:
- Incident ID: `INC` followed by 10–12 digits (e.g. `INC00027452650`)
- Timestamp token: `DDMMYYYY-HHMM` (e.g. `05062025-0606`)
Example: `INC00027452650-05062025-0606.vtt`

## Running the App
Ensure dependencies are installed using `uv`:
```bash
uv sync
uv run streamlit run app.py
```
This will create necessary folders under `data/` on first run.

## Pipeline Overview
Each stage implements `Stage.run(ctx, params)` returning `StageOutput` objects containing:
- `trc_outputs`: values persisted to the TRC entry
- `trc_artifacts_text` / `trc_artifacts_json`: artifact files
- `incident_updates`: keys merged at incident level (e.g. `master_summary`, `keywords`)
- `people_directory_updates`: discovered people, roles, knowledge

Order and enablement come from `config.json` (editable in the UI). Stages may declare `requires` dependencies; the pipeline performs a stable topological sort and reports configuration errors early.

## Re-running From a Stage
Within the TRC Library view, choose a starting stage (or "Start") to re-run downstream processing. Upstream prerequisites are automatically backfilled.

## People Directory
The people directory (`data/people/people_directory.json`) accumulates discovered roles and knowledge. Manual overrides (display name, canonical role) and deletions are supported via the UI.

## Configuration
The Configuration page lets you:
- Reorder pipeline stages.
- Enable/disable stages.
- Edit per-stage JSON params.
- Clear the people directory.

## Logging
Logs are written to `app.log` and streamed to console via `setup_logging()`.

## Development
Install dependencies and run tests & lint:
```bash
uv sync
uv run ruff check .
uv run pytest -q
```
Format code:
```bash
uv run ruff format .
```

## Git Hygiene
Avoid committing anything under `data/` (artifacts, uploads, incidents, people directory), virtual environments, or build caches. See `.gitignore` for full list.

## Future Improvements
- Authentication / access control
- Pagination & search UX enhancements
- Additional NLP stages (sentiment, action items)
- Bulk export features

## License
(Insert appropriate license information here, if applicable.)
