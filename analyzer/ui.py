import base64
import json
import os
import re
from pathlib import Path

import streamlit as st

from .design import apply_theme, wordmark
from .finance import calculate
from .ingestion import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .pdf_export import legacy_parts, memo_pdf
from .pipeline import Jobs, Pipeline
from .storage import Repository


@st.cache_resource
def jobs():
    return Jobs()


def delete_analysis(record, repo, manager, owner):
    identifier = record["id"]
    if manager.active((owner, identifier)):
        st.error("Cancel the running analysis before deleting it.")
        return
    try:
        if record.get("storage") == "local":
            repo.delete_legacy(identifier)
        else:
            repo.delete(identifier)
    except Exception:
        st.error("Could not delete this analysis. Please try again.")
        return
    for key in ("active_run", "legacy_memo"):
        if st.session_state.get(key) == identifier:
            st.session_state.pop(key, None)
    st.session_state.history_notice = "Analysis deleted."
    st.rerun()


def analysis_header(record, repo, manager, owner, title=None, date=None, pdf_markdown=None):
    title = title or record["company_name"]
    date = date or str(record.get("created_at", ""))[:10]
    with st.container(key="memo-title"):
        st.header(title)
    date_column, action_column = st.columns([5, 1.35], vertical_alignment="center")
    with date_column:
        if date:
            st.caption(f"Analyzed {date}")
    with action_column:
        with st.popover("Actions", icon=":material/more_horiz:", width="content", key="memo-actions"):
            if pdf_markdown is not None:
                pdf = memo_pdf(title, date, pdf_markdown)
                filename = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-").lower() or "investment-memo"
                st.download_button("Save as PDF", pdf, file_name=f"{filename}.pdf",
                                   mime="application/pdf", icon=":material/picture_as_pdf:", width="stretch")
            if st.button("Delete analysis", icon=":material/delete:", key="delete-analysis-" + record["id"],
                         disabled=manager.active((owner, record["id"])), width="stretch"):
                delete_analysis(record, repo, manager, owner)


def auth(app):
    if not app.is_supabase_enabled() or app.get_current_user():
        return True

    mode = st.session_state.get("auth_mode", "sign_in")
    st.subheader("Private access")

    if mode == "sign_up":
        st.caption("Create an account for this private workspace.")
        with st.form("create-account-form"):
            email = st.text_input("Email", key="sign-up-email", autocomplete="username")
            password = st.text_input(
                "New password", type="password", key="sign-up-password", autocomplete="new-password"
            )
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            ok, message = app.sign_up_user(email, password)
            if ok and app.get_current_user():
                st.rerun()
            (st.success if ok else st.error)(message)
        if st.button("Back to sign in", key="show-sign-in"):
            st.session_state.auth_mode = "sign_in"
            st.rerun()
    else:
        st.caption("Sign in to your private workspace.")
        with st.form("sign-in-form"):
            email = st.text_input("Email", key="sign-in-email", autocomplete="username")
            password = st.text_input(
                "Password", type="password", key="sign-in-password", autocomplete="current-password"
            )
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            ok, message = app.sign_in_user(email, password)
            if ok and app.get_current_user():
                st.rerun()
            (st.success if ok else st.error)(message)
        if st.button("Create an account", key="show-sign-up"):
            st.session_state.auth_mode = "sign_up"
            st.rerun()
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
    if not (st.session_state.get("active_run") or st.session_state.get("legacy_memo")):
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
        st.html('<div class="workspace-label" style="padding-top:18px">ANALYSIS HISTORY</div>')
        try:
            records = repo.list()
            if not user:
                records += app.list_saved_memos()
            for record in records:
                label = record["company_name"]
                if st.button(label, key="history-" + record["id"], width="stretch"):
                    if record.get("storage") == "local":
                        st.session_state.legacy_memo = record["id"]
                        st.session_state.pop("active_run", None)
                    else:
                        st.session_state.active_run = record["id"]
                        st.session_state.pop("legacy_memo", None)
                    st.rerun()
            if notice := st.session_state.pop("history_notice", None):
                st.success(notice)
        except Exception:
            st.error("Could not load private history. Check your storage connection.")
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
            fallback_date = str(memo.get("created_at", ""))[:10]
            title, date, body = legacy_parts(memo["memo_content"], memo["company_name"], fallback_date)
            analysis_header(memo, repo, manager, owner, title, date, body)
            st.markdown(app.format_memo_for_display(body))
        return

    if st.session_state.get("active_run"):
        identifier = st.session_state.active_run
        if notice := st.session_state.pop("submission_notice", None):
            st.info(notice)
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
                    fallback_date = str(memo.get("created_at", ""))[:10]
                    title, date, body = legacy_parts(memo["memo_content"], memo["company_name"], fallback_date)
                    analysis_header(memo, repo, manager, owner, title, date, body)
                    st.markdown(app.format_memo_for_display(body))
                return
            if state["status"] == "complete":
                analysis_header(state, repo, manager, owner, pdf_markdown=state["result"]["summary"])
                show_result(state)
                return
            analysis_header(state, repo, manager, owner)
            if state["status"] == "queued" and manager.active((owner, identifier)):
                st.info("Queued — your files are saved. Analysis will start automatically when your current analysis finishes.")
                st.caption("You can browse your history while you wait. You don't need to upload these files again.")
            elif manager.active((owner, identifier)):
                st.info(f"Analysis in progress · {state['phase']}")
                st.caption("Your submission is saved. This page updates automatically; no need to submit again.")
            else:
                st.info("Analysis paused — select Resume analysis to continue." if state["status"] in {"queued", "running"} else state["phase"])
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
        files = st.file_uploader("Company materials", type=["pdf", "csv", "tsv", "xlsx", "txt", "md"], accept_multiple_files=True)
        st.caption("Upload files for one company. The first filename becomes the company name. 15 MB per file, 25 MB total.")
        submit = st.form_submit_button("Analyze investment", type="primary", width="stretch", icon=":material/arrow_forward:")
    if submit:
        if not files:
            st.error("Upload at least one file to analyze.")
            return
        if not app.ANTHROPIC_API_KEY:
            st.error("Configure ANTHROPIC_API_KEY to run analysis.")
            return
        documents = [{"name": file.name, "data": base64.b64encode(file.getvalue()).decode()} for file in files]
        if any(file.size > MAX_FILE_BYTES for file in files):
            st.error("Each file must be no larger than 15 MB.")
            return
        if sum(file.size for file in files) > MAX_TOTAL_BYTES:
            st.error("Upload at most 25 MB total per analysis.")
            return
        # Avoid collisions in document downloads and redundant extraction.
        documents = list({item["data"]: item for item in documents}.values())
        name = re.sub(r"[_\s]+", " ", Path(files[0].name).stem).strip() or "Untitled company"
        inputs = dict(company_name=name, website="", stage="Infer from evidence", business_model="Infer from evidence",
                      description="", terms="", thesis=app.INVESTMENT_THESIS,
                      model=os.getenv("ANALYSIS_MODEL", "claude-sonnet-4-5-20250929"), max_requests=80,
                      scenario_assumptions={"retained_fraction": 0.5, "holding_years": 7.0,
                                            "fee_fraction": 0.0, "carry_fraction": 0.0})
        try:
            with st.spinner("Checking your files and saving the submission…"):
                state, created = manager.submit(owner, repo, inputs, documents, app.ANTHROPIC_API_KEY, app.TAVILY_API_KEY)
            st.session_state.active_run = state["id"]
            st.session_state.submission_notice = (
                "Files received. Your analysis has been submitted — no need to upload again."
                if created else "These files already have an analysis. Opening the existing entry instead of creating a duplicate."
            )
        except Exception:
            st.error("Could not start or save the analysis. Check the API and storage configuration.")
            return
        st.rerun()
