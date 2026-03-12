# Shark Tank

Private Streamlit app for angel-investment diligence using CrewAI, Anthropic, Tavily, and uploaded startup documents.

## Local run

Create a `.env` file with:

```env
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...
```

Then run:

```bash
source venv/bin/activate
streamlit run run.py
```

## Deploy on Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. In Streamlit Community Cloud, create a new app from that repo.
3. Set the main file path to `run.py`.
4. Add these secrets in the Streamlit app settings:

```toml
ANTHROPIC_API_KEY = "your_key_here"
TAVILY_API_KEY = "your_key_here"
```

5. Deploy.

The app reads secrets from either environment variables or Streamlit secrets, so the same code works locally and in Streamlit Cloud.

## Current cloud limitation

Memo history is currently stored on local disk in `investment_memos/`. That works locally, but on most free cloud hosts it is not durable across restarts or redeploys.

If you want reliable cloud history, the next step is to move memo storage to a database or object store.

## Main dependencies

- `streamlit`
- `crewai`
- `anthropic`
- `tavily-python`
- `PyMuPDF`
- `python-dotenv`
