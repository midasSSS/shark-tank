# Shark Tank

Private Streamlit app for angel-investment diligence using CrewAI, Anthropic, Tavily, and uploaded startup documents.

## Local run

Create a `.env` file with:

```env
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
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
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_ANON_KEY = "your_supabase_anon_key"
```

5. Deploy.

The app reads secrets from either environment variables or Streamlit secrets, so the same code works locally and in Streamlit Cloud.

## Supabase setup

This app now supports private per-user memo history when Supabase is configured.

1. Create a Supabase project.
2. In Supabase Auth, enable Email auth.
3. Run the SQL in [`supabase_schema.sql`](/Users/macallan/PycharmProjects/playground/investment-analyzer/supabase_schema.sql) in the SQL editor.
4. Copy your project URL and anon key into local `.env` or Streamlit secrets.
5. Deploy or restart the app.

With Supabase enabled:

- users must sign in before using the app
- each user only sees their own memos
- memo history persists across restarts and redeploys

Without Supabase configured, the app falls back to local file storage.

## Current cloud limitation

Uploaded source PDFs are still transient and are not stored in cloud storage yet. Only the final memo content is persisted to Supabase.

If you want reliable cloud document retention too, the next step is to add object storage for uploaded files.

## Main dependencies

- `streamlit`
- `crewai`
- `anthropic`
- `tavily-python`
- `supabase`
- `PyMuPDF`
- `python-dotenv`
