import base64
import json
import os

import streamlit as st

from .design import apply_theme, breadcrumb, section, storage_badge, wordmark
from .finance import calculate
from .ingestion import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .pipeline import Jobs, Pipeline
from .storage import Repository


@st.cache_resource
def jobs():
    return Jobs()


def auth(app):
    if not app.is_supabase_enabled() or app.get_current_user():
        return True
    st.subheader("Private access")
    for tab, label in zip(st.tabs(["Sign in", "Create account"]), ["Sign in", "Create account"]):
        with tab, st.form(label):
            email = st.text_input("Email", key=label + "email")
            password = st.text_input("Password", type="password", key=label + "password")
            if st.form_submit_button(label):
                ok, message = (app.sign_in_user if label == "Sign in" else app.sign_up_user)(email, password)
                if ok and app.get_current_user():
                    st.rerun()
                (st.success if ok else st.error)(message)
    return False


def show_result(state):
    result = state["result"]
    with st.container(key="decision-card"):
        st.html('<div class="eyebrow">INVESTMENT DECISION</div>')
        st.markdown(result["summary"])
        st.download_button("Download summary", result["summary"], file_name="investment-summary.md", mime="text/markdown")
    with st.expander("Evidence and sources"):
        steps = state["steps"]
        sources = steps.get("ingestion", {}).get("sources", []) + steps.get("research", {}).get("sources", [])
        used = set(result["decision"]["source_ids"]) | set(result["hundred"]["source_ids"]) | set(result["defensive"]["source_ids"])
        for source in sources:
            if source["id"] in used:
                st.write(f"{source['id']} · {source['title']} · {source['location']}")
                if source.get("url"):
                    st.link_button("Open source", source["url"])
                    st.caption(f"Retrieved {source['retrieved_at']} · {source.get('coverage', '')}")
        st.dataframe(steps.get("evidence", {}).get("facts", []), width="stretch")
        for warning in dict.fromkeys(steps.get("evidence", {}).get("coverage_gaps", []) + steps.get("evidence", {}).get("conflicts", [])):
            st.caption(warning)
        for index, document in enumerate(state.get("documents", [])):
            st.download_button(f"Download {document['name']}", base64.b64decode(document["data"]),
                               file_name=document["name"], key=state["id"] + str(index))
    with st.expander("100× and downside assessments"):
        for title, key in [("100× potential", "hundred"), ("Downside protection", "defensive")]:
            st.subheader(title)
            assessment = result[key]
            st.write("Qualifies" if assessment["qualifies"] and not assessment["blockers"] else "Not established")
            for reason in assessment["reasons"]:
                st.write(reason)
            st.write("Required outcome:", assessment["required_outcome"])
            st.write("Main risk:", assessment["main_risk"])
            for blocker in assessment["blockers"]:
                st.caption(blocker)
    with st.expander("Calculations and sensitivity"):
        e = state["steps"]["economics"]
        calc = state["steps"]["calculation"]
        st.json(calc)
        st.caption("Scenario assumptions; changing these does not rewrite the saved recommendation.")
        if calc.get("supported"):
            retained = st.slider("Ownership retained after future dilution", 0.05, 1.0, float(e["retained_fraction"]), 0.05, key=state["id"] + "sensitivity")
            changed = calculate(dict(e, retained_fraction=retained))
            st.metric("Exit equity value required for 100×", f"{e['currency']} {changed['required_exit_for_100x']:,.0f}")
            rows = []
            for multiplier in (0.5, 0.75, 1.0, 1.25, 1.5):
                sensitivity = calculate(dict(e, entry_post_money=e["entry_post_money"] * multiplier, retained_fraction=retained))
                if sensitivity.get("supported"):
                    rows.append({"Entry price vs offered": multiplier, "Required exit for 100×": sensitivity["required_exit_for_100x"],
                                 "Base net MOIC": sensitivity.get("scenarios", {}).get("base", {}).get("net_moic")})
            st.dataframe(rows, width="stretch")
        st.json(e)
        st.json(state["steps"].get("review", {}))
    with st.expander("Analysis record"):
        st.caption(f"Model: {state['model']} · Framework: {state['prompt_version']} · As of {state['created_at']}")
        usage = state.get("usage", [])
        st.write(f"Tokens: {sum(v['input_tokens'] for v in usage):,} input / {sum(v['output_tokens'] for v in usage):,} output")
        st.caption("Dollar cost unavailable: provider pricing is not configured. Public research freshness is the retrieval timestamp; rerun for new information.")
        st.download_button("Download complete analysis and evidence", json.dumps(state, indent=2),
                           file_name="analysis-record.json", mime="application/json")


def main(app):
    st.set_page_config(page_title="Investment Analyzer", page_icon="↗", layout="wide")
    apply_theme()
    breadcrumb(bool(st.session_state.get("active_run") or st.session_state.get("legacy_memo")))
    st.title("Investment Analyzer")
    st.html('<p class="page-intro">Find the exceptional. Understand the downside.<br>A clear investment decision, grounded in the evidence.</p>')
    if os.getenv("LOCAL_MODE", "").strip().lower() not in {"1", "true", "yes"} and not app.is_supabase_enabled():
        st.error("Configure Supabase for private cloud access, or start on loopback with LOCAL_MODE=1 for local use.")
        return
    if not auth(app):
        return
    user = app.get_current_user()
    owner = user["id"] if user else "local"
    repo = Repository(app.get_supabase_client() if user else None, owner if user else None)
    manager = jobs()
    with st.sidebar:
        wordmark()
        if st.button("New analysis", key="new-analysis", icon=":material/add:", width="stretch"):
            st.session_state.pop("active_run", None)
            st.session_state.pop("legacy_memo", None)
            st.rerun()
        query = st.text_input("Search companies", placeholder="Search companies…", label_visibility="collapsed", icon=":material/search:")
        st.html('<div class="workspace-label" style="padding-top:18px">ANALYSIS HISTORY</div>')
        try:
            records = repo.list()
            if not user:
                records += app.list_saved_memos()
            for record in records:
                if query.casefold() not in record["company_name"].casefold():
                    continue
                label = f"{record['company_name']} · {str(record.get('created_at', ''))[:10]}"
                if st.button(label, key="history-" + record["id"], width="stretch"):
                    if record.get("storage") == "local":
                        st.session_state.legacy_memo = record["id"]
                        st.session_state.pop("active_run", None)
                    else:
                        st.session_state.active_run = record["id"]
                        st.session_state.pop("legacy_memo", None)
                    st.rerun()
        except Exception:
            st.error("Could not load private history. Check your storage connection.")
        storage_badge(bool(user))
        if user and st.button("Sign out"):
            active = st.session_state.get("active_run")
            if active:
                manager.stop((owner, active))
            app.sign_out_user()
            for key in list(st.session_state):
                del st.session_state[key]
            st.rerun()

    if st.session_state.get("legacy_memo"):
        memo = app.load_memo(st.session_state.legacy_memo)
        if memo:
            st.caption("Legacy memo — source evidence was not saved with this analysis.")
            st.markdown(app.format_memo_for_display(memo["memo_content"]))
        return

    if st.session_state.get("active_run"):
        identifier = st.session_state.active_run
        polling = manager.active((owner, identifier))

        @st.fragment(run_every="2s" if polling else None)
        def live():
            if polling and not manager.active((owner, identifier)):
                st.rerun()
            try:
                state = repo.load(identifier)
            except Exception:
                st.error("Could not read the saved analysis. Check your private storage connection and refresh.")
                return
            if state is None:
                memo = app.load_memo(identifier)
                if memo:
                    st.caption("Legacy memo — evidence unavailable")
                    st.markdown(app.format_memo_for_display(memo["memo_content"]))
                return
            st.subheader(state["company_name"])
            if state["status"] == "complete":
                show_result(state)
                return
            st.info(state["phase"])
            st.caption(f"{len(state['steps'])} saved steps · {state['status']}")
            if manager.active((owner, identifier)):
                if st.button("Cancel analysis"):
                    manager.stop((owner, identifier))
                    st.info("Cancellation requested; the current provider request may take up to its timeout.")
            else:
                st.caption("Completed steps will be reused. After an app restart, resume here.")
                if state.get("errors"):
                    st.warning(state.get("failure_message", "The last request failed."))
                if state.get("failure_message") and state["errors"][-1]["type"] == "RequestBudgetExceeded":
                    limit = st.number_input("New total model-request limit", min_value=state.get("request_count", 0) + 1,
                                            value=state.get("request_count", 0) + 20, step=10)
                    state["inputs"]["max_requests"] = limit
                if st.button("Resume analysis", disabled=not app.ANTHROPIC_API_KEY):
                    manager.start((owner, identifier), Pipeline(repo, state, app.ANTHROPIC_API_KEY, app.TAVILY_API_KEY))
                    st.rerun()
        live()
        return

    with st.form("decision_input"):
        section("01", "The company", "Start with the opportunity you’re considering.")
        left, right = st.columns(2)
        with left:
            name = st.text_input("Company name", placeholder="e.g. Acme", max_chars=150)
        with right:
            website = st.text_input("Website (optional)", placeholder="https://company.com", help="A public company website, used with the company name for research. Private documents are not sent as search queries.")
        left, right = st.columns(2)
        with left:
            stage = st.selectbox("Stage", ["Infer from evidence", "Early stage", "Growth stage", "Pre-IPO"])
        with right:
            business = st.text_input("Business model (optional)", placeholder="SaaS, marketplace, hardware…")
        description = st.text_area("Company context (optional)", placeholder="What does the company do? What stands out?", height=85)
        st.divider()
        section("02", "The opportunity", "The price and the evidence behind the pitch.")
        terms = st.text_area("Offered price and deal terms", placeholder="Valuation, share class or SAFE terms, investment amount, fees and carry…", height=95)
        files = st.file_uploader("Available company materials", type=["pdf", "csv", "tsv", "xlsx", "txt", "md"], accept_multiple_files=True, label_visibility="collapsed")
        st.caption("Decks, financials, terms or notes · 15 MB per file, 25 MB total")
        with st.expander("Scenario assumptions and investment thesis"):
            st.caption("Illustrative assumptions, disclosed in your result. Documented terms take precedence.")
            retained = st.slider("Ownership retained after future dilution", 0.05, 1.0, 0.5, 0.05)
            years = st.number_input("Scenario holding period (years)", min_value=1.0, max_value=40.0, value=7.0)
            fee = st.number_input("Assumed upfront fee (% of total outlay)", min_value=0.0, max_value=50.0, value=0.0)
            carry = st.number_input("Assumed carry (% of profit)", min_value=0.0, max_value=50.0, value=0.0)
            max_requests = st.number_input("Maximum model requests for this run", min_value=10, max_value=500, value=80, step=10)
            thesis = st.text_area("Investment thesis", value=app.INVESTMENT_THESIS, height=180)
        submit = st.form_submit_button("Analyze investment", type="primary", width="stretch", icon=":material/arrow_forward:")
        st.caption("A concise invest / pass decision. No founder follow-ups. Missing critical evidence means pass.")
    if submit:
        if not name.strip():
            st.error("Enter a company name.")
            return
        if not app.ANTHROPIC_API_KEY:
            st.error("Configure ANTHROPIC_API_KEY to run analysis.")
            return
        if website and not website.startswith(("https://", "http://")):
            st.error("Use a full public website URL beginning with https:// or http://.")
            return
        documents = [{"name": file.name, "data": base64.b64encode(file.getvalue()).decode()} for file in files]
        if any(file.size > MAX_FILE_BYTES for file in files):
            st.error("Each file must be no larger than 15 MB.")
            return
        if sum(file.size for file in files) > MAX_TOTAL_BYTES:
            st.error("Upload at most 25 MB total per analysis.")
            return
        # Avoid collisions in document downloads and redundant extraction.
        documents = list({(item["name"], item["data"]): item for item in documents}.values())
        inputs = dict(company_name=name.strip(), website=website.strip(), stage=stage, business_model=business,
                      description=description, terms=terms, thesis=thesis,
                      model=os.getenv("ANALYSIS_MODEL", "claude-sonnet-4-5-20250929"), max_requests=max_requests,
                      scenario_assumptions={"retained_fraction": retained, "holding_years": years,
                                            "fee_fraction": fee / 100, "carry_fraction": carry / 100})
        try:
            state = repo.create(inputs, documents)
            st.session_state.active_run = state["id"]
            manager.start((owner, state["id"]), Pipeline(repo, state, app.ANTHROPIC_API_KEY, app.TAVILY_API_KEY))
        except Exception:
            st.error("Could not start or save the analysis. Check the API and storage configuration.")
            return
        st.rerun()
