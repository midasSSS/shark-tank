"""
AI-Powered Angel Investment Diligence Tool
Uses CrewAI + Claude Sonnet 4.5 + Tavily for comprehensive startup analysis
"""

import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
import streamlit as st
from dotenv import load_dotenv
import fitz  # PyMuPDF

# CrewAI telemetry tries to register process signal handlers, which breaks
# when analysis runs in a worker thread to keep the Streamlit UI responsive.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from crewai import Agent, Task, Crew, Process, LLM
from anthropic import Anthropic

# Load environment variables
load_dotenv()


def get_secret(name: str) -> Optional[str]:
    """Read a secret from env vars first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    return st.secrets.get(name)


# Verify API keys
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")
TAVILY_API_KEY = get_secret("TAVILY_API_KEY")

if not ANTHROPIC_API_KEY:
    st.error("⚠️ ANTHROPIC_API_KEY not found in .env file")
if not TAVILY_API_KEY:
    st.warning("⚠️ TAVILY_API_KEY not found - web research will be limited")

# Investment thesis (hard-coded as per requirements)
INVESTMENT_THESIS = """
You are helping me evaluate investment opportunities. My investment philosophy is as follows:

What I back: I am fully agnostic on industry and stage — I will invest in pre-seed through growth, in deep tech or 
consumer, in regulated industries or emerging markets. What I care about is not the sector or the moment in a company's 
life — it is the caliber of what is being built and who is building it.

What I look for in companies: I back companies that are remarkable — meaning they are doing something that genuinely 
matters, with a point of view that is non-consensus and correct, and an ambition that is commensurate with the size of 
the problem they are attacking. Remarkable companies have earned or are on a clear path to earn an asymmetric position 
in their market — not through luck or timing alone, but through genuine insight and relentless execution. They make you 
feel that the world would be worse without them.

What I look for in people: I back founders and teams who are themselves remarkable — meaning they possess an unusual 
combination of domain obsession, intellectual honesty, and the will to push through what would stop most others. 
I want to see evidence that they understand their market more deeply than anyone else, that they attract and retain 
exceptional talent, and that they have the self-awareness to know what they don't know. Charisma matters less to me 
than conviction backed by substance.

What I am not looking for: I am not looking for companies chasing consensus trends, incremental improvements, or d
efensible mediocrity. I am not looking for founders who are optimizing for a safe outcome. I am not looking for ideas 
that require the world to be more forgiving than it actually is.

How to use this thesis: When I share a company, a pitch, a founder profile, or a market with you, evaluate it through 
this lens. Push back where something looks ordinary dressed up as exceptional. Help me find signal in what founders say 
and don't say. Ask the questions a great investor would ask — the ones that reveal whether the people and the idea are 
truly remarkable, or just good.
"""

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_text_from_pdf(pdf_file) -> str:
    """
    Extract text from uploaded PDF using PyMuPDF.
    Preserves layout structure as much as possible.
    """
    try:
        pdf_bytes = pdf_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        full_text = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            full_text.append(f"--- Page {page_num + 1} ---\n{text}")

        doc.close()
        return "\n\n".join(full_text)
    except Exception as e:
        st.error(f"Error extracting PDF text: {str(e)}")
        return ""


def sanitize_filename(name: str) -> str:
    """Create safe filename from company name."""
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')


def save_memo(company_name: str, memo_content: str) -> str:
    """Save investment memo to file and return filepath."""
    output_dir = Path("./investment_memos")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sanitize_filename(company_name)}_{timestamp}.md"
    filepath = output_dir / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(memo_content)

    return str(filepath)


def list_saved_memos() -> List[Path]:
    """Return saved memo files in reverse chronological order."""
    output_dir = Path("./investment_memos")
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)


def format_memo_history_label(filepath: Path) -> str:
    """Create a readable sidebar label from a saved memo filename."""
    company_name, timestamp = parse_memo_metadata(filepath)
    if not company_name or not timestamp:
        return filepath.name
    return f"{company_name} • {timestamp.strftime('%b %d, %Y %H:%M')}"


def parse_memo_metadata(filepath: Path) -> tuple[Optional[str], Optional[datetime]]:
    """Extract company name and saved timestamp from a memo filename."""
    stem = filepath.stem
    match = re.match(r"(.+?)_(\d{8})_(\d{6})$", stem)
    if not match:
        return None, None

    company_slug, date_part, time_part = match.groups()
    company_name = company_slug.replace("_", " ")
    timestamp = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")
    return company_name, timestamp


def load_memo(filepath: Path) -> str:
    """Load a saved memo from disk."""
    return filepath.read_text(encoding="utf-8")


def open_selected_history_memo() -> None:
    """Open the memo currently selected in the sidebar history."""
    selected_path = st.session_state.get("memo_history_selection")
    if selected_path:
        st.session_state.selected_memo_path = selected_path
        st.session_state.view_mode = "history"


def format_memo_for_display(memo_content: str) -> str:
    """
    Format memo content for proper LaTeX rendering in Streamlit.
    Ensures proper spacing around display math blocks and escapes
    currency-style dollar amounts so Streamlit doesn't parse them as math.
    """
    # Temporarily protect real LaTeX blocks so we can safely escape currency.
    latex_placeholders: dict[str, str] = {}

    def protect_latex(match: re.Match) -> str:
        placeholder = f"__LATEX_{len(latex_placeholders)}__"
        latex_placeholders[placeholder] = match.group(0)
        return placeholder

    def is_latex_inline(content: str) -> bool:
        """Heuristically distinguish real inline math from dollar-denominated prose."""
        stripped = content.strip()
        if not stripped:
            return False

        latex_markers = ["\\", "{", "}", "^", "_", "=", "\\times", "\\frac", "\\text"]
        if any(marker in stripped for marker in latex_markers):
            return True

        # Preserve compact finance/math expressions like CAC/LTV or ARR/MRR,
        # but avoid treating normal prose between two currency values as math.
        compact_pattern = r"^[A-Za-z0-9%().,+\-/*:<>\s]{1,24}$"
        looks_compact = re.fullmatch(compact_pattern, stripped) is not None
        contains_math_signal = any(char in stripped for char in ["/", "+", "-", "*", "<", ">"])
        is_currency_like = bool(re.match(r"^\d", stripped)) or any(token in stripped.lower() for token in ["million", "billion"])

        return looks_compact and contains_math_signal and not is_currency_like

    def protect_inline_latex(match: re.Match) -> str:
        content = match.group(1)
        if is_latex_inline(content):
            return protect_latex(match)
        # Treat non-math $...$ spans as malformed currency/prose and
        # collapse them back to plain text with a literal leading dollar sign.
        return rf"\${content}"

    memo_content = re.sub(r"\$\$.*?\$\$", protect_latex, memo_content, flags=re.DOTALL)
    memo_content = re.sub(r"(?<!\\)\$([^$\n]+)\$", protect_inline_latex, memo_content)

    # Escape any remaining dollar markers that are not protected LaTeX.
    memo_content = re.sub(r"(?<!\\)\$", r"\\$", memo_content)

    # Ensure display math blocks have blank lines around them
    memo_content = re.sub(r'([^\n])\n\$\$', r'\1\n\n$$', memo_content)
    memo_content = re.sub(r'\$\$\n([^\n])', r'$$\n\n\1', memo_content)

    # Clean up excessive blank lines (more than 2)
    memo_content = re.sub(r'\n{4,}', '\n\n\n', memo_content)

    # Restore real LaTeX blocks.
    for placeholder, latex_block in latex_placeholders.items():
        memo_content = memo_content.replace(placeholder, latex_block)

    return memo_content


def run_crew_analysis(crew: Crew, result_holder: dict, done_event: threading.Event) -> None:
    """Run the CrewAI analysis in a worker thread so Streamlit can keep updating the UI."""
    try:
        result_holder["result"] = crew.kickoff()
    except Exception as exc:
        result_holder["error"] = exc
    finally:
        done_event.set()


def estimate_analysis_phase(elapsed_seconds: float) -> tuple[int, str]:
    """
    Provide a best-effort progress estimate while the analysis is running.
    CrewAI doesn't expose live task callbacks here, so we surface an elapsed-time
    based phase indicator to reassure the user that work is still moving.
    """
    phases = [
        (12, 12, "Researching founders, market, and recent signals..."),
        (24, 32, "Reading uploaded documents and extracting traction details..."),
        (40, 52, "Evaluating valuation, terms, and financial quality..."),
        (58, 72, "Scoring conviction, risks, and diligence questions..."),
        (78, 88, "Drafting and refining the investment memo..."),
        (95, 96, "Finalizing output and preparing the memo for display..."),
    ]

    for threshold, progress_value, label in phases:
        if elapsed_seconds < threshold:
            return progress_value, label

    # Hold near-complete until the actual analysis finishes.
    return 97, "Wrapping up the final analysis..."


# ============================================================================
# CREWAI AGENTS
# ============================================================================

def create_agents():
    """Create specialized agents for startup analysis."""

    # Configure Claude Sonnet 4.5 LLM for CrewAI
    llm = LLM(
        model="anthropic/claude-sonnet-4-5-20250929",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.7
    )

    # Agent 1: Research Agent
    researcher = Agent(
        role="Startup Research Analyst",
        goal="Gather comprehensive information about the startup, founders, market, and competitors through web research",
        backstory="""You are an expert at due diligence research with 15 years of experience in venture capital. 
        You excel at finding relevant information about founders' backgrounds, market dynamics, competitive landscape, 
        and any news or red flags. You synthesize findings clearly and cite sources.""",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

    # Agent 2: Document Analyst
    document_analyst = Agent(
        role="Document & Pitch Analyst",
        goal="Extract and analyze key information from AngelList exports, pitch decks, and company materials",
        backstory="""You are a meticulous analyst who specializes in reading startup documents and extracting 
        critical data points. You can identify traction metrics, team qualifications, product details, 
        and business model information from dense PDFs. You're skeptical and look for substantiation.""",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

    # Agent 3: Financial & Terms Analyst
    financial_analyst = Agent(
        role="Financial & Terms Analyst",
        goal="Evaluate valuation, deal terms, cap table, SAFE structure, and financial metrics",
        backstory="""You are a financial analyst with deep expertise in early-stage startup valuations and deal structures. 
        You can assess whether terms are fair, identify problematic clauses, benchmark against market standards, 
        and evaluate financial sustainability. You understand SAFEs, convertible notes, equity rounds, and cap table dynamics.""",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

    # Agent 4: Thesis & Scoring Agent
    thesis_agent = Agent(
        role="Investment Thesis & Scoring Analyst",
        goal="Evaluate startup fit against investment thesis and assign detailed scores",
        backstory=f"""You are an experienced angel investor who applies a rigorous investment framework. 
        Your thesis is: {INVESTMENT_THESIS}
        
        You score startups objectively across multiple dimensions and provide clear justifications. 
        You are direct about weaknesses and conservative in scoring.""",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

    # Agent 5: Investment Memo Writer
    memo_writer = Agent(
        role="Investment Memo Writer",
        goal="Synthesize all analysis into a clear, actionable investment memo with specific format",
        backstory="""You are a senior investment professional who writes clear, concise, and actionable investment memos. 
        You synthesize complex information, highlight key insights, identify risks clearly, and make strong recommendations. 
        Your memos are structured, professional, and decision-oriented.""",
        verbose=True,
        allow_delegation=False,
        llm=llm
    )

    return researcher, document_analyst, financial_analyst, thesis_agent, memo_writer


# ============================================================================
# CREWAI TASKS
# ============================================================================

def create_tasks(agents, context: dict):
    """Create tasks for the crew based on input context."""

    researcher, document_analyst, financial_analyst, thesis_agent, memo_writer = agents

    # Build context summary
    context_summary = f"""
Company Name: {context['company_name']}
Description: {context['description']}
Terms/Valuation Info: {context['terms']}
"""

    # Task 1: Web Research
    research_task = Task(
        description=f"""Conduct comprehensive web research on this startup:
        {context_summary}
        
        Research the following using multiple targeted searches:
        1. Founder backgrounds (LinkedIn, previous companies, expertise, credibility)
        2. Market size and growth trends for this sector
        3. Direct and indirect competitors
        4. Recent news, funding announcements, or red flags
        5. Industry validation (awards, partnerships, press coverage)
        
        For each research area, formulate specific search queries and synthesize findings.
        Provide a structured summary with sources cited.
        
        Example searches you should conduct:
        - "[Founder name] LinkedIn background"
        - "[Company name] competitors"
        - "[Market/industry] market size 2024"
        - "[Company name] news funding"
        """,
        agent=researcher,
        expected_output="Comprehensive research report with founder backgrounds, market analysis, competitive landscape, and recent news/developments with sources cited.",
        async_execution=False
    )

    # Task 2: Document Analysis
    doc_text_preview = context['pdf_text'][:30000] if context['pdf_text'] else 'No PDF provided'

    doc_analysis_task = Task(
        description=f"""Analyze the provided document text to extract critical information:
        
        AngelList/Pitch Deck Text:
        {doc_text_preview}
        
        Extract and analyze:
        1. Team composition and founder qualifications
        2. Product/service details and unique value proposition
        3. Traction metrics (revenue, ARR/MRR, users, growth rates, retention)
        4. Business model and go-to-market strategy
        5. Technology/IP details and competitive moat
        6. Customer profiles and validation
        7. Any claims that need verification
        
        Be critical and flag unsupported claims or missing information.""",
        agent=document_analyst,
        expected_output="Detailed extraction of team, product, traction, business model, and technology details with critical assessment of claims.",
        context=[research_task],
        async_execution=False
    )

    # Task 3: Financial & Terms Analysis
    financial_task = Task(
        description=f"""Analyze the financial and deal terms:
        
        Terms Information:
        {context['terms']}
        
        Document Text (for financial data):
        {doc_text_preview}
        
        Evaluate:
        1. Valuation (pre/post-money cap if SAFE, or valuation if priced round)
        2. Deal structure (SAFE, convertible note, equity - analyze terms)
        3. Dilution implications for investors
        4. Discount rates, valuation caps, pro-rata rights
        5. Financial metrics: burn rate, runway, unit economics, CAC/LTV
        6. Red flags in terms (excessive liquidation preferences, problematic clauses)
        7. Benchmark against market standards for this stage/sector
        
        Provide clear assessment of whether terms are reasonable and investor-friendly.""",
        agent=financial_analyst,
        expected_output="Comprehensive financial and terms analysis with valuation assessment, deal structure evaluation, and market benchmark comparison.",
        context=[doc_analysis_task],
        async_execution=False
    )

    # Task 4: Thesis Alignment & Scoring
    scoring_task = Task(
        description=f"""Evaluate this startup against our investment thesis and assign scores:
        
        Investment Thesis:
        {INVESTMENT_THESIS}
        
        Using all prior research and analysis, score the following (1-10 scale with 1-sentence justification each):
        1. Team / Founder Fit
        2. Market Size & Timing
        3. Product / Traction / Moat
        4. Competition / Differentiation
        5. Terms / Valuation / Structure
        6. Overall Conviction
        
        Also identify:
        - Key Strengths (4-7 bullets)
        - Red Flags / Risks (5-10 bullets - be direct and critical)
        - 8-12 high-quality, specific questions to ask founders
        
        Be objective and conservative in scoring. A score of 7+ is very good.""",
        agent=thesis_agent,
        expected_output="Detailed scoring (1-10) with justifications, key strengths, red flags/risks, and specific due diligence questions.",
        context=[research_task, doc_analysis_task, financial_task],
        async_execution=False
    )

    # Task 5: Investment Memo
    memo_task = Task(
        description=f"""Synthesize all analysis into a comprehensive investment memo following this EXACT format.

CRITICAL FORMATTING RULES:
- Use proper markdown with blank lines between sections
- For mathematical formulas, use LaTeX notation:
  * Inline math: $formula$ (e.g., $CAC/LTV$ or $ARR$)
  * Display math: $$formula$$ on its own line with blank lines before/after
  * Example: $$ROI = \\frac{{Revenue - Cost}}{{Cost}} \\times 100$$
- Escape backslashes in LaTeX (use \\\\ for commands like \\frac, \\times)
- Add blank lines between all paragraphs and sections
- Use bullet points with proper spacing (- item)
- Make the memo highly readable and professional

# Investment Memo: [Company Name]

**Date:** {datetime.now().strftime('%B %d, %Y')}

---

## 1. Executive Summary

[Write 1 well-formatted paragraph summary of opportunity, key metrics, and recommendation. Include proper spacing.]

---

## 2. Scores

- **Team / Founder Fit:** [Score]/10 - [1-sentence justification]
- **Market Size & Timing:** [Score]/10 - [1-sentence justification]
- **Product / Traction / Moat:** [Score]/10 - [1-sentence justification]
- **Competition / Differentiation:** [Score]/10 - [1-sentence justification]
- **Terms / Valuation / Structure:** [Score]/10 - [1-sentence justification]
- **Overall Conviction:** [Score]/10 - [1-sentence justification]

---

## 3. Key Strengths

- [Strength 1]
- [Strength 2]
- [Strength 3]
- [Strength 4]
- [Additional strengths as applicable, up to 7 total]

---

## 4. Red Flags / Risks

- [Risk 1 - be direct and specific]
- [Risk 2]
- [Risk 3]
- [Risk 4]
- [Risk 5]
- [Additional risks as applicable, up to 10 total]

---

## 5. Due Diligence Questions

1. [Specific, high-quality question 1]
2. [Question 2]
3. [Question 3]
4. [Question 4]
5. [Question 5]
6. [Question 6]
7. [Question 7]
8. [Question 8]
9. [Additional questions as applicable, up to 12 total]

---

## 6. Comparable Deals / Benchmarks

[Provide stage, valuation, and traction comparisons. Cite real examples if found from research. Format as readable paragraphs with proper spacing. Use inline math for metrics where appropriate, e.g., $5M ARR at $50M valuation.]

---

## 7. Go / No-Go Recommendation

**Recommendation:** [GO / NO-GO / MAYBE]

[Write 2-3 well-formatted paragraphs with clear reasoning. Include proper paragraph breaks. Be decisive and actionable.]

---

## 8. Full Investment Memo

### Overview

[Write 2-3 paragraphs covering company, market, and product overview. Use proper spacing between paragraphs.]

### Thesis Fit

[Write 2-3 paragraphs explaining how this aligns or doesn't align with our investment thesis. Use proper spacing.]

### Analysis

[Write 3-5 paragraphs with deep dive on team, market, product, traction, and competition. Break into readable chunks with proper spacing. Use LaTeX for financial metrics where appropriate.]

### Risks

[Write 2-3 paragraphs with detailed risk analysis. Use proper spacing between paragraphs.]

### Recommendation

[Write final 2-3 paragraphs with clear recommendation, reasoning, and next steps. Use proper spacing.]

---

IMPORTANT: 
- Synthesize ALL information from previous agent analyses
- Be professional, direct, and decision-oriented
- Use proper markdown and LaTeX formatting throughout
- Ensure the memo is actionable and helps make a clear investment decision""",
        agent=memo_writer,
        expected_output="Complete investment memo in exact specified markdown format with proper LaTeX rendering, all sections, scores, analysis, and recommendation.",
        context=[research_task, doc_analysis_task, financial_task, scoring_task],
        async_execution=False
    )

    return [research_task, doc_analysis_task, financial_task, scoring_task, memo_task]


# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    st.set_page_config(
        page_title="Angel Investment Analyzer",
        page_icon="📊",
        layout="wide"
    )

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1.25rem;
            padding-bottom: 1rem;
        }
        div[data-testid="stVerticalBlock"] div[data-testid="stMarkdownContainer"] p {
            line-height: 1.5;
        }
        .memo-shell {
            padding: 1rem 0 0.25rem 0;
        }
        .memo-meta {
            color: #6b7280;
            font-size: 0.9rem;
            margin-bottom: 0.1rem;
        }
        .memo-title {
            font-size: 1.35rem;
            font-weight: 650;
            margin-bottom: 0.2rem;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label {
            border: 1px solid #d1d5db;
            border-radius: 0.9rem;
            padding: 0.8rem 0.95rem;
            margin-bottom: 0.75rem;
            width: 100%;
            box-sizing: border-box;
            display: flex;
            align-items: flex-start;
            gap: 0.25rem;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease, background-color 160ms ease;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            transform: translateY(-1px);
            border-color: #9ca3af;
            background: #fcfcfd;
            box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label[data-checked="true"] {
            border-color: #9ca3af;
            background: #f8fafc;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
            display: none;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] p {
            margin: 0;
            line-height: 1.2;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] p:first-child {
            font-size: 1rem;
            font-weight: 600;
            color: #111827;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] p:last-child {
            font-size: 0.82rem;
            color: #6b7280;
            margin-top: 0.15rem;
        }
        section[data-testid="stSidebar"] .new-analysis-button .stButton > button {
            position: relative;
            width: 100%;
            box-sizing: border-box;
            border-radius: 0.95rem;
            padding: 0.8rem 1rem;
            font-weight: 600;
            text-align: center;
            background:
                linear-gradient(135deg, rgba(255, 0, 153, 0.18), rgba(0, 229, 255, 0.14) 38%, rgba(255, 214, 10, 0.16) 72%, rgba(120, 119, 255, 0.18)),
                linear-gradient(180deg, #16181d 0%, #0f1115 100%);
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            color: white !important;
            box-shadow: 0 14px 34px rgba(10, 14, 24, 0.34) !important;
            overflow: hidden;
        }
        section[data-testid="stSidebar"] .new-analysis-button .stButton > button:hover {
            background:
                linear-gradient(135deg, rgba(255, 0, 153, 0.24), rgba(0, 229, 255, 0.18) 38%, rgba(255, 214, 10, 0.2) 72%, rgba(120, 119, 255, 0.24)),
                linear-gradient(180deg, #1b1e24 0%, #111318 100%);
            border-color: rgba(255, 255, 255, 0.14) !important;
            color: white !important;
        }
        section[data-testid="stSidebar"] .new-analysis-button .stButton > button::before {
            content: "";
            position: absolute;
            inset: 0;
            padding: 1px;
            border-radius: inherit;
            background: linear-gradient(120deg, rgba(255, 0, 153, 0.85), rgba(0, 229, 255, 0.85), rgba(255, 214, 10, 0.85), rgba(120, 119, 255, 0.85));
            -webkit-mask:
                linear-gradient(#fff 0 0) content-box,
                linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
            pointer-events: none;
            opacity: 0.9;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.title("🦈💰 Shark Tank")

    if "selected_memo_path" not in st.session_state:
        st.session_state.selected_memo_path = None
    if "view_mode" not in st.session_state:
        st.session_state.view_mode = "new"
    if "memo_history_selection" not in st.session_state:
        st.session_state.memo_history_selection = None

    saved_memos = list_saved_memos()
    if saved_memos and not st.session_state.selected_memo_path:
        st.session_state.selected_memo_path = str(saved_memos[0])
    if (
        saved_memos
        and st.session_state.view_mode == "history"
        and st.session_state.selected_memo_path in [str(path) for path in saved_memos]
    ):
        st.session_state.memo_history_selection = st.session_state.selected_memo_path

    # Sidebar history
    with st.sidebar:
        st.markdown('<div class="new-analysis-button">', unsafe_allow_html=True)
        if st.button("Start Analysis", use_container_width=True, type="secondary"):
            st.session_state.selected_memo_path = None
            st.session_state.view_mode = "new"
            st.session_state.memo_history_selection = None
        st.markdown('</div>', unsafe_allow_html=True)
        st.write("")
        st.header("🗂️ Analysis History")
        if saved_memos:
            st.caption("Choose a memo")
            memo_options = [str(path) for path in saved_memos]
            memo_titles = []
            memo_dates = []
            for memo_path in saved_memos:
                company_name, timestamp = parse_memo_metadata(memo_path)
                memo_titles.append(company_name or memo_path.stem)
                memo_dates.append(
                    timestamp.strftime('%b %d, %Y %H:%M')
                    if timestamp
                    else memo_path.name
                )

            selected_index = (
                memo_options.index(st.session_state.selected_memo_path)
                if (
                    st.session_state.view_mode == "history"
                    and st.session_state.selected_memo_path in memo_options
                )
                else None
            )
            selected_memo_path = st.radio(
                "Past analyzed companies",
                options=memo_options,
                index=selected_index,
                captions=memo_dates,
                format_func=lambda path: memo_titles[memo_options.index(path)],
                key="memo_history_selection",
                on_change=open_selected_history_memo,
                label_visibility="collapsed"
            )
            if st.session_state.view_mode == "history":
                st.session_state.selected_memo_path = selected_memo_path
        else:
            st.caption("No saved analyses yet. Run one and it will appear here.")

    if st.session_state.view_mode == "history" and st.session_state.selected_memo_path:
        selected_memo_file = Path(st.session_state.selected_memo_path)
        if selected_memo_file.exists():
            st.divider()
            with st.container(border=True):
                st.markdown('<div class="memo-shell">', unsafe_allow_html=True)
                saved_memo_content = format_memo_for_display(load_memo(selected_memo_file))
                st.markdown(saved_memo_content)
                st.download_button(
                    label="⬇️ Download Saved Memo",
                    data=saved_memo_content,
                    file_name=selected_memo_file.name,
                    mime="text/markdown",
                    use_container_width=True,
                    key=f"download_saved_{selected_memo_file.name}"
                )
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.session_state.selected_memo_path = None
    else:
        with st.expander("How this works", expanded=False):
            st.markdown("""
            1. Enter company name and description
            2. Add deal terms or valuation if available
            3. Upload the AngelList export and optionally a pitch deck
            4. Click **Analyze Startup**

            The AI will research the market, analyze the documents, evaluate the terms, score the opportunity against your thesis, and generate a memo.
            """)

        with st.expander("Current Investment Thesis"):
            st.info(INVESTMENT_THESIS)

        # Main input form
        with st.form("startup_input_form"):
            st.subheader("Company Information")

            col1, col2 = st.columns(2)

            with col1:
                company_name = st.text_input(
                    "Company Name *",
                    placeholder="e.g., Acme AI Corp"
                )

                description = st.text_area(
                    "Description / Link",
                    placeholder="Brief description or link to company website/AngelList profile",
                    height=100
                )

            with col2:
                terms = st.text_area(
                    "Terms / SAFE / Valuation (optional)",
                    placeholder="e.g., $10M cap SAFE, 20% discount, $500K raise",
                    height=100
                )

            st.divider()

            col3, col4 = st.columns(2)

            with col3:
                angellist_pdf = st.file_uploader(
                    "AngelList Export PDF *",
                    type=['pdf'],
                    help="Upload the AngelList prospect export PDF"
                )

            with col4:
                pitch_deck_pdf = st.file_uploader(
                    "Pitch Deck PDF (optional)",
                    type=['pdf'],
                    help="Upload pitch deck for additional analysis"
                )

            submit_button = st.form_submit_button("🔍 Analyze", use_container_width=True)

        # Process analysis
        if submit_button:
        # Validation
            if not company_name:
                st.error("❌ Please enter a company name")
                return

            if not ANTHROPIC_API_KEY:
                st.error("❌ Anthropic API key not configured. Please add to .env file")
                return

            # Extract PDF text
            pdf_text = ""

            if angellist_pdf:
                with st.spinner("📄 Extracting text from AngelList PDF..."):
                    pdf_text += extract_text_from_pdf(angellist_pdf)
                    st.success(f"✅ Extracted {len(pdf_text)} characters from AngelList PDF")

            if pitch_deck_pdf:
                with st.spinner("📄 Extracting text from Pitch Deck..."):
                    deck_text = extract_text_from_pdf(pitch_deck_pdf)
                    pdf_text += f"\n\n--- PITCH DECK ---\n\n{deck_text}"
                    st.success(f"✅ Extracted {len(deck_text)} characters from Pitch Deck")

            # Build context
            context = {
                'company_name': company_name,
                'description': description or "No description provided",
                'terms': terms or "No terms information provided",
                'pdf_text': pdf_text
            }

            # Run CrewAI analysis
            try:
            # Progress indicator
                progress_header = st.empty()
                progress_bar = st.progress(0)
                progress_text = st.empty()
                elapsed_text = st.empty()
                phase_list = st.empty()

                progress_header.info("🤖 AI agents are analyzing the startup. Live progress will update here during the 3-5 minute run.")
                progress_text.text("Creating specialized AI agents...")
                phase_list.markdown(
                    "- Research founders, market, and competitors\n"
                    "- Analyze uploaded documents and traction\n"
                    "- Evaluate terms, valuation, and financials\n"
                    "- Score conviction and draft the memo"
                )
                progress_bar.progress(5)

                # Create agents and tasks
                agents = create_agents()
                progress_text.text("Defining analysis tasks...")
                progress_bar.progress(10)
                tasks = create_tasks(agents, context)

                # Create and run crew
                progress_text.text("Orchestrating multi-agent analysis...")
                progress_bar.progress(15)
                crew = Crew(
                    agents=list(agents),
                    tasks=tasks,
                    process=Process.sequential,
                    verbose=True
                )

                result_holder: dict = {}
                done_event = threading.Event()
                worker = threading.Thread(
                    target=run_crew_analysis,
                    args=(crew, result_holder, done_event),
                    daemon=True
                )

                worker.start()
                start_time = time.time()

                while not done_event.is_set():
                    elapsed_seconds = int(time.time() - start_time)
                    progress_value, phase_label = estimate_analysis_phase(elapsed_seconds)
                    progress_bar.progress(progress_value)
                    progress_text.text(phase_label)
                    elapsed_text.caption(
                        f"Elapsed time: {elapsed_seconds // 60}:{elapsed_seconds % 60:02d} "
                        f"(typical runtime is 3-5 minutes)"
                    )
                    time.sleep(0.5)

                worker.join()

                if "error" in result_holder:
                    raise result_holder["error"]

                progress_bar.progress(100)
                progress_text.text("Analysis complete. Preparing memo...")
                elapsed_seconds = int(time.time() - start_time)
                elapsed_text.caption(
                    f"Finished in {elapsed_seconds // 60}:{elapsed_seconds % 60:02d}"
                )

                # Extract final memo
                result = result_holder["result"]
                memo_content = str(result.raw)

                # Format for proper LaTeX rendering
                memo_content = format_memo_for_display(memo_content)

                # Display result
                progress_header.success("✅ Analysis complete!")

                st.divider()
                st.subheader("📝 Investment Memo")

                # Display memo with LaTeX support
                st.markdown(memo_content)

                # Save memo
                filepath = save_memo(company_name, memo_content)
                st.session_state.selected_memo_path = filepath
                st.session_state.memo_history_selection = filepath
                st.session_state.view_mode = "history"
                st.success(f"💾 Memo saved to: `{filepath}`")

                # Download button
                st.download_button(
                    label="⬇️ Download Investment Memo (Markdown)",
                    data=memo_content,
                    file_name=f"{sanitize_filename(company_name)}_memo.md",
                    mime="text/markdown",
                    use_container_width=True
                )

            except Exception as e:
                st.error(f"❌ Analysis failed: {str(e)}")
                st.exception(e)

                # Show helpful debugging info
                with st.expander("🔍 Debugging Information"):
                    st.write("**Error details:**")
                    st.code(str(e))
                    st.write("**Context:**")
                    st.json({
                        "company_name": company_name,
                        "has_description": bool(description),
                        "has_terms": bool(terms),
                        "pdf_text_length": len(pdf_text),
                        "anthropic_key_configured": bool(ANTHROPIC_API_KEY),
                        "tavily_key_configured": bool(TAVILY_API_KEY)
                    })


if __name__ == "__main__":
    main()


# source venv/bin/activate
# streamlit run run.py
