# Investment Analyzer improvement plan

## Product objective

Deliver a short **INVEST / PASS** recommendation from uploaded materials and available public information, for early-stage, growth-stage, and pre-IPO investments.

An investment must qualify through at least one of two paths:

1. **100× potential:** a credible path to returning 100 times the investor’s capital at the offered terms, after modeled dilution and applicable fees/carry.
2. **Downside protection:** an evidence-backed case for comparatively lower capital-loss risk and a worthwhile return at the offered price.

These paths are independent of stage. Growth companies may qualify for the first; pre-IPO companies do not automatically qualify for the second. “Safe” is interpreted as relative downside protection, never a guarantee. The user's loss tolerance, minimum acceptable return, and holding horizon are not yet specified; do not fabricate these preferences or claim suitability against them.

No founder follow-up questions, outreach, diligence-request workflow, or mandatory manual review. Resolve uncertainties using available documents and public sources. If decision-critical information remains unavailable, return **PASS — insufficient evidence**, distinguishing that from a negative judgment about the business.

## Default output

Target 100–150 words, with supporting sources and calculations expandable:

- **Verdict:** INVEST or PASS.
- **Basis:** 100× potential / downside protection / neither established.
- **Why:** two or three company- and deal-specific reasons.
- **Return case:** required outcome for 100×, or the modeled base/downside outcome and holding period for the downside-protection path.
- **Main risk:** the single most consequential failure mode or evidence gap.
- **Evidence confidence:** high / medium / low, with a short explanation. This is confidence in the evidence, not a probability of investment success.

No default long memo, numerical company scorecard, MAYBE verdict, or list of questions. Detailed analysis remains available on demand. INVEST is a recommendation only; the app does not execute transactions.

## Decision logic

### Path A: credible 100× potential

- Evaluate the actual security and entry terms, not merely whether the company could become large.
- Calculate the required exit equity value after dilution, instrument conversion, preferences, fees and carry where applicable. Keep enterprise value distinct from equity proceeds.
- Illustrative simple-equity math, before fees and preferences: investor multiple = exit equity value / entry post-money valuation × retained ownership fraction. A $20m entry valuation with 50% ownership retention requires a $4bn exit equity value for 100×. This is scenario arithmetic, not a forecast; SAFEs and complex securities require their own calculations.
- Work backward from that exit to the necessary revenue, margins, market share, financing and time. Compare those requirements with sourced market evidence and the company's differentiation, team and progress.
- Separate “mathematically possible” from a credible investment thesis. A large TAM or an invented optimistic exit alone cannot qualify a deal.
- Show financing/failure risks and the dependence on exceptional execution. Do not invent success probabilities or treat 100× as an expected return.

### Path B: evidence-backed downside protection

- Assess business durability, financial reporting quality, cash generation or funded runway, debt, customer concentration and capital needs using appropriate business-model metrics.
- Assess price paid, share class, preference seniority, transaction structure, transfer restrictions, and direct ownership versus SPV exposure. Include fees and carry where known.
- Stress test slower growth, lower exit multiples, further dilution and an IPO delay or no IPO. A modeled downside is not a maximum possible loss.
- Require a supported case for capital preservation and worthwhile returns under explicitly disclosed assumptions. Do not equate a famous company, prior funding valuation or planned IPO with safety.
- If material financials, price or security terms cannot be established, this path cannot support INVEST.
- Keep user-level return/horizon/loss thresholds configurable; until set, describe the assessment as qualitative and show scenario assumptions rather than silently introducing numerical suitability thresholds.

### Combining the paths

Recommend INVEST only if at least one path has a credible, sufficiently supported case and no unresolved issue invalidates that case. Otherwise recommend PASS, with a reason such as insufficient evidence, implausible 100× outcome, excessive entry price, or weak downside protection. Evaluate both paths when evidence permits and surface the qualifying basis.

Preserve the original thesis about remarkable companies and founders as qualitative evidence within this return-focused framework. Brand or founder appeal cannot override unfavorable deal economics.

## Current implementation gaps

Reviewed `run.py`, `README.md`, `requirements.txt`, and `supabase_schema.sql`:

- The research agent has no search tool attached despite prompts requesting web research and citations. The Tavily key is checked without an implemented search integration.
- Document and financial analysis receive only the first 30,000 characters of extracted PDF text. Later pages, charts, tables and scanned text can be missed.
- The five-agent workflow produces a long fixed memo, generic scores and 8–12 founder questions. These conflict with the requested experience.
- Terms are free text and financial outputs are LLM prose. There is no inspectable return model or 100× qualification rule.
- Stage and business model are not structured inputs, despite the thesis spanning pre-seed through growth.
- Supabase stores final memos and basic inputs, but not sources, structured metrics, scenarios or run snapshots.
- UI progress is time-based rather than actual step completion; runs lack durable recovery.
- `run.py` contains existing uncommitted changes; implementation must preserve them.

## Implementation sequence

### 1. Build the short verdict pipeline and reliable evidence together

- Replace the fixed memo/scoring/question prompts with typed evidence, path assessments and the brief verdict schema.
- Accept company identity, optional stage/business model, deal terms and available files. Make AngelList optional and infer classifications when supported.
- Wire real search and retrieval; preserve URLs, dates and supporting passages. Verify company identity and distinguish founder claims from external corroboration.
- Replace silent truncation with page-aware extraction/retrieval across complete documents, with visible extraction gaps. Add scanned-page/table handling where required by the initial cases.
- Store provenance for material facts: value, currency/unit, period, definition and source/page. Detect conflicts automatically; do not force the user into a review workflow.
- Apply the insufficient-evidence PASS rule when research fails or extraction gaps prevent a supported decision. Never imply research succeeded when it did not.
- Treat document and web content as evidence, not executable instructions. Do not send confidential document contents as external search queries.

### 2. Implement the two return paths

- Add deterministic calculations for supported equity, SAFE/note conversions, dilution and exit proceeds. Explicitly reject unsupported structures instead of approximating them silently.
- Add reverse 100× calculations and downside/base/upside scenarios, including holding periods and vehicle costs where known.
- Extract stage-appropriate evidence: founder insight and early validation for early stage; revenue quality, durability and cash generation for growth/pre-IPO. Avoid forcing SaaS metrics onto other businesses.
- Use documented qualitative qualification criteria tied to evidence. Do not hide the decision behind arbitrary 1–10 scores.
- Ensure verdict prose uses the same numbers and assumptions as the calculation outputs.

### 3. Persist evidence and make execution dependable

- Incrementally separate UI, schemas, extraction, research, calculations, decision logic and storage. Keep Streamlit.
- Persist documents privately, source evidence, scenarios and run snapshots; extend existing owner-based access controls to all records and objects.
- Retain concise history by company with verdict, basis, date and input versions. Preserve legacy memos without inventing their missing evidence.
- Add actual progress events, bounded retries/timeouts, cached extraction and run recovery. Record prompt/model versions and usage/cost where available.
- Preserve raw data independently of Markdown formatting. Avoid confidential source text in verbose logs and test account switching.

## First release acceptance criteria

- A supported early-stage case can qualify on credible 100× economics; a large TAM alone cannot.
- A promising company at an excessive price can receive PASS.
- A pre-IPO company with thin financial evidence or weak downside economics receives PASS even if well known.
- Unknown entry price or material security terms cannot produce an unsupported INVEST.
- A lower-risk case can qualify without 100× potential, with explicit downside/return assumptions and no guarantee language.
- Material evidence beyond 30,000 characters is included or its omission is disclosed and affects the decision.
- Calculation fixtures reconcile dilution, equity value, fees and supported preference structures; prose matches the calculated results.
- No case generates founder questions or requires company outreach.
- Default results fit approximately 100–150 words, with citations and optional supporting detail.
- Stored documents and analyses remain isolated between users.

Use synthetic or permissioned early-stage, growth and pre-IPO fixtures, including missing terms, conflicting financials and failed research. Assess unsupported claims, citation correctness, calculation accuracy and verdict consistency. Implementation is now present in `analyzer/` and the updated Streamlit entry point. See README.md for supported financial structures, runtime limits and verification commands.

## Deferred scope

Founder follow-ups and outreach are excluded. CRM features, portfolio monitoring, additional agents, frontend replacement and expansive dashboards are deferred. The immediate deliverable is a reliable, concise investment recommendation.

## Risk terminology reference

The SEC notes that pre-IPO investments can involve significant risk, including total loss, and that private placements are highly illiquid. These constraints inform the downside-protection path rather than adding generic disclaimers to every result.

- [SEC: Pre-IPO Investment Scams — Investor Alert](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/investor-48)
- [SEC: Private Placements — Investor Bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/private)

## Implementation notes

The initial implementation includes the short verdict UI, actual research, complete text segmentation, specialist analysis/verification stages, deterministic supported-structure calculations, evidence retention, checkpoint recovery and tests. Specialist stages now use the Anthropic SDK directly instead of CrewAI.

Original documents and structured checkpoints use the existing private memo table in cloud mode; separate normalized tables and object storage are deferred scaling work. Complex securities and dated multi-cash-flow IRR remain explicitly unsupported. OCR depends on local Tesseract support; unreadable charts/pages are disclosed, not treated as successfully extracted. Dollar cost is not displayed without configured pricing.
