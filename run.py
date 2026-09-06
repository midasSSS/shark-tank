"""
Private Investment Analyzer
Evidence-backed INVEST/PASS recommendations for early-stage, growth and pre-IPO deals
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import streamlit as st
from dotenv import load_dotenv
import fitz  # PyMuPDF
from supabase import Client, create_client

# Load environment variables
load_dotenv()


def get_secret(name: str) -> Optional[str]:
    """Read a secret from env vars first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except FileNotFoundError:
        return None


# Verify API keys
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")
TAVILY_API_KEY = get_secret("TAVILY_API_KEY")

if not ANTHROPIC_API_KEY:
    st.error("⚠️ ANTHROPIC_API_KEY not found in .env file")
if not TAVILY_API_KEY:
    st.warning("⚠️ TAVILY_API_KEY not found - web research will be limited")

# Default thesis; each analysis saves its own editable version.
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


def is_supabase_enabled() -> bool:
    """Return whether cloud auth and storage are configured."""
    if os.getenv("LOCAL_MODE", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_ANON_KEY"))


def get_supabase_client() -> Optional[Client]:
    """Create or return the Supabase client for this session."""
    if not is_supabase_enabled():
        return None

    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            get_secret("SUPABASE_URL"),
            get_secret("SUPABASE_ANON_KEY")
        )

        auth_tokens = st.session_state.get("auth_tokens")
        if auth_tokens:
            try:
                st.session_state.supabase_client.auth.set_session(
                    auth_tokens["access_token"],
                    auth_tokens["refresh_token"]
                )
            except Exception:
                st.session_state.auth_tokens = None
                st.session_state.auth_user = None

    return st.session_state.supabase_client


def persist_auth_session(session: Any, user: Any) -> None:
    """Persist auth details into Streamlit session state."""
    st.session_state.auth_tokens = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }
    st.session_state.auth_user = {
        "id": str(user.id),
        "email": user.email,
    }


def clear_auth_session() -> None:
    """Clear auth details and app state for logout."""
    st.session_state.auth_tokens = None
    st.session_state.auth_user = None
    st.session_state.selected_memo_path = None
    st.session_state.memo_history_selection = None
    st.session_state.view_mode = "new"


def get_current_user() -> Optional[Dict[str, str]]:
    """Return the authenticated user when Supabase is enabled."""
    if not is_supabase_enabled():
        return None
    return st.session_state.get("auth_user")


def sign_in_user(email: str, password: str) -> tuple[bool, str]:
    """Sign in against Supabase email/password auth."""
    client = get_supabase_client()
    if not client:
        return False, "Supabase is not configured."

    try:
        response = client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        if response.session and response.user:
            persist_auth_session(response.session, response.user)
            st.session_state.view_mode = "new"
            st.session_state.selected_memo_path = None
            st.session_state.memo_history_selection = None
            return True, ""
        return False, "Login failed."
    except Exception as exc:
        return False, str(exc)


def sign_up_user(email: str, password: str) -> tuple[bool, str]:
    """Create a new Supabase auth user."""
    client = get_supabase_client()
    if not client:
        return False, "Supabase is not configured."

    try:
        response = client.auth.sign_up({
            "email": email,
            "password": password,
        })
        if response.session and response.user:
            persist_auth_session(response.session, response.user)
            st.session_state.view_mode = "new"
            return True, "Account created and signed in."
        return True, "Account created. Check your email if confirmation is enabled."
    except Exception as exc:
        return False, str(exc)


def sign_out_user() -> None:
    """Sign out the current Supabase user."""
    client = get_supabase_client()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    clear_auth_session()


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse timestamps from local files or database rows."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def format_history_timestamp(timestamp: Optional[datetime]) -> str:
    """Format timestamps consistently for the sidebar."""
    if not timestamp:
        return "Unknown date"
    return timestamp.strftime("%b %d, %Y %H:%M")


def save_memo_locally(company_name: str, memo_content: str) -> str:
    """Save investment memo to local file storage and return filepath."""
    output_dir = Path("./investment_memos")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sanitize_filename(company_name)}_{timestamp}.md"
    filepath = output_dir / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(memo_content)

    return str(filepath)


def save_memo(
    company_name: str,
    memo_content: str,
    description: str = "",
    terms: str = "",
) -> Dict[str, Any]:
    """Save investment memo to cloud storage when configured, else local disk."""
    current_user = get_current_user()
    client = get_supabase_client()

    if client and current_user:
        result = client.table("memos").insert({
            "owner_id": current_user["id"],
            "company_name": company_name,
            "description": description,
            "terms": terms,
            "memo_content": memo_content,
        }).execute()
        row = result.data[0]
        return {
            "id": row["id"],
            "company_name": row["company_name"],
            "created_at": parse_timestamp(row.get("created_at")),
            "memo_content": row["memo_content"],
            "storage": "cloud",
        }

    filepath = save_memo_locally(company_name, memo_content)
    company_name, created_at = parse_memo_metadata(Path(filepath))
    return {
        "id": filepath,
        "company_name": company_name or Path(filepath).stem,
        "created_at": created_at,
        "memo_content": memo_content,
        "storage": "local",
    }


def list_saved_memos() -> List[Dict[str, Any]]:
    """Return saved memos in reverse chronological order."""
    current_user = get_current_user()
    client = get_supabase_client()

    if client and current_user:
        result = client.table("memos").select(
            "id, company_name, created_at"
        ).order("created_at", desc=True).execute()
        return [
            {
                "id": row["id"],
                "company_name": row["company_name"],
                "created_at": parse_timestamp(row.get("created_at")),
                "storage": "cloud",
            }
            for row in result.data
        ]

    output_dir = Path("./investment_memos")
    if not output_dir.exists():
        return []
    paths = sorted(output_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "id": str(path),
            "company_name": parse_memo_metadata(path)[0] or path.stem,
            "created_at": parse_memo_metadata(path)[1],
            "storage": "local",
        }
        for path in paths
    ]


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


def load_memo(memo_id: str) -> Optional[Dict[str, Any]]:
    """Load a memo from cloud storage or local disk."""
    current_user = get_current_user()
    client = get_supabase_client()

    if client and current_user:
        result = client.table("memos").select(
            "id, company_name, created_at, memo_content"
        ).eq("id", memo_id).limit(1).execute()
        if result.data:
            row = result.data[0]
            return {
                "id": row["id"],
                "company_name": row["company_name"],
                "created_at": parse_timestamp(row.get("created_at")),
                "memo_content": row["memo_content"],
                "storage": "cloud",
            }
        return None

    filepath = Path(memo_id)
    if not filepath.exists():
        return None
    company_name, created_at = parse_memo_metadata(filepath)
    return {
        "id": str(filepath),
        "company_name": company_name or filepath.stem,
        "created_at": created_at,
        "memo_content": filepath.read_text(encoding="utf-8"),
        "storage": "local",
        "filename": filepath.name,
    }


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


def main():
    import sys
    from analyzer.ui import main as render
    render(sys.modules[__name__])


if __name__ == "__main__":
    main()
