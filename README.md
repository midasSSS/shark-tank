# Investment Analyzer

Private Streamlit app for a short **INVEST / PASS** decision on early-stage, growth-stage and pre-IPO companies.

The recommendation must be supported by **credible 100× net investor potential** or **evidence-backed downside protection**. It uses available documents and public information; it never generates founder follow-up questions. Missing decision-critical evidence results in PASS. Pre-IPO status does not establish safety.

## Start locally

```bash
source venv/bin/activate
pip install -r requirements.txt
LOCAL_MODE=1 streamlit run run.py --server.address 127.0.0.1
```

Open http://localhost:8501. Local mode skips authentication and stores private analysis records under `investment_memos/runs/`, even when Supabase credentials exist. Keep the local server bound to loopback. You may alternatively set `LOCAL_MODE=1` in your local `.env`.

Configure `.env` or Streamlit secrets:

```env
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...
```

`ANALYSIS_MODEL` optionally overrides the default `claude-sonnet-4-5-20250929`. An Anthropic key is needed to analyze. Without Tavily, the research gap is explicit and the final decision cannot be INVEST. Never commit credentials or source documents.

## Workflow

1. Upload available PDFs, CSV/TSV, XLSX or text files for one company. The first filename becomes the company name. Limits: 15 MB per file and 25 MB total.
2. Select Analyze investment. Stage, business model and terms are assessed from the evidence. The existing default thesis and disclosed scenario assumptions are applied automatically.
3. Read the result. The default result is a short verdict, qualifying basis, reasons, return case, main risk and evidence confidence.

Evidence, cited sources, original documents, path assessments, calculation inputs, price/dilution sensitivities and the complete analysis record are available in expanders. Scenario controls do not rewrite the saved recommendation. No transactions are executed.

## Analysis architecture

- `analyzer/ingestion.py`: complete page-aware extraction, PDF tables, OCR fallback, spreadsheet formula-cache warnings, text splitting without silent truncation.
- `analyzer/models.py`: validated evidence, economics and recommendation schemas.
- `analyzer/pipeline.py`: real Tavily research and checkpointed specialist stages for evidence extraction, financial analysis, verification, upside, downside and decision writing. Uses the Anthropic SDK directly; CrewAI is no longer required.
- `analyzer/finance.py`: deterministic ownership, dilution, fees/carry, reverse 100× and exit-scenario calculations; explicit decision gates.
- `analyzer/storage.py`: versioned private records, original documents, evidence, input/thesis/model versions and intermediate checkpoints.
- `analyzer/ui.py`: input, concise verdict, private history, actual phase progress, cancellation/resume and sensitivity controls.
- `run.py`: entry point, authentication and legacy memo compatibility.

Research queries contain only the public company name and website. Uploaded content is sent to the configured model for analysis, not included in external search queries. Source quotations are checked against retrieved text. Company identity, conflicting metrics and material gaps receive a separate verification pass. Citations establish provenance, not an independent guarantee that reported claims are true.

## Calculation scope

Supported structures are simple equity without material preference/debt-waterfall complications and post-money SAFEs where cap conversion ownership is established. Unknown terms, pre-money SAFEs, notes and complex preference stacks are explicitly unsupported and cannot yield INVEST.

Scenario fees are fractions of total initial outlay. Carry is charged on positive profit above that outlay. The calculator models one initial investment and one exit; the annualized result is not an IRR for multiple dated cash flows. Exit values are equity values, not enterprise values.

The 100× path requires a credible analyst assessment and a modeled upside of at least 100× net. The downside path requires a supported qualitative assessment, modeled downside of at least 1× and base above 1×. These are screening conditions, not a guarantee or personalized return/risk thresholds. Missing critical inputs, unresolved material conflicts, unconfirmed identity and low evidence confidence block INVEST.

## Resume, budgets and extraction limits

Uploads are deduplicated by file contents, regardless of filenames or order; repeated submissions open the existing analysis. One analysis per user runs at a time in this app process, with additional submissions queued automatically. The queue and concurrent-submission lock are process-local; multiple app replicas would require a shared queue and database uniqueness constraint. Legacy Markdown-only memos lack source files and cannot be matched automatically. Completed steps are saved and reused on retry. After an app restart, open the company from history and select Resume. Cancellation takes effect between bounded provider requests. A model-request budget defaults to 80 and can be increased if reached. Input/output token usage is recorded; dollar cost is unavailable until pricing is configured externally. Source length determines runtime and usage; evidence extraction processes up to four segments per model call.

Each run is an immutable research/input snapshot for analytical purposes. Start a new analysis to refresh public research or change original inputs. Interrupted runs retain their original inputs and retrieved evidence. Very large collected evidence is stopped with an explicit context-limit error rather than silently truncated.

PDF text/table extraction cannot reliably interpret every chart. Scanned pages attempt OCR using the locally available Tesseract support; unavailable OCR, images/charts and unreadable content are disclosed as coverage gaps and assessed for materiality. XLSX formulas need cached values from a spreadsheet application. The app does not evaluate spreadsheet formulas or macros.

## Private cloud deployment

Leave `LOCAL_MODE` unset. Configure these additional Streamlit secrets:

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_ANON_KEY = "your_anon_key"
```

Enable Supabase email authentication and run `supabase_schema.sql` for a new database. Cloud mode requires valid configuration and sign-in. The existing owner-based row-level-security policies cover the new records; no migration is necessary if the original schema already exists.

New analyses are serialized as versioned JSON inside `memos.memo_content`, including base64 original documents. This keeps checkpoint writes and document privacy under the existing RLS policy. It is deliberately a small-app storage approach: larger deployments should move document blobs to private object storage and normalize record metadata. Legacy Markdown memos remain readable and are labeled as lacking saved evidence.

## Verification

```bash
venv/bin/python -m unittest discover -s tests -v
```

Tests cover return arithmetic, unsupported inputs, conservative verdict gates, long-document coverage, spreadsheet warnings, fabricated quotations, checkpoint recovery/cancellation, private record handling, legacy compatibility, local authentication bypass and the Streamlit result screen. Provider integration checks can use synthetic material; do not use confidential company files merely to test a connection.
