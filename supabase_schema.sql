create table if not exists public.memos (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    company_name text not null,
    description text default '',
    terms text default '',
    memo_content text not null,
    created_at timestamptz not null default now()
);

alter table public.memos enable row level security;

drop policy if exists "Users can read their own memos" on public.memos;
create policy "Users can read their own memos"
on public.memos
for select
using (auth.uid() = owner_id);

drop policy if exists "Users can insert their own memos" on public.memos;
create policy "Users can insert their own memos"
on public.memos
for insert
with check (auth.uid() = owner_id);

drop policy if exists "Users can update their own memos" on public.memos;
create policy "Users can update their own memos"
on public.memos
for update
using (auth.uid() = owner_id)
with check (auth.uid() = owner_id);

drop policy if exists "Users can delete their own memos" on public.memos;
create policy "Users can delete their own memos"
on public.memos
for delete
using (auth.uid() = owner_id);
