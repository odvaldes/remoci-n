-- Ejecutar en el SQL Editor de Supabase para guardar solicitudes de prueba.
-- La política permite insertar solicitudes anónimas, pero no leerlas desde la app.

create table if not exists public.georiskai_requests (
    id uuid primary key,
    created_at timestamptz not null default now(),
    address text not null,
    comuna text not null,
    event_type text not null,
    built_m2 double precision not null default 0,
    unbuilt_m2 double precision not null default 0,
    contact_name text,
    email text,
    phone text,
    requested_services jsonb not null default '[]'::jsonb,
    consent_ai boolean not null default false,
    consent_provider_sharing boolean not null default false,
    consent_training_photos boolean not null default false,
    analysis_status text not null,
    assessment jsonb,
    budget_min_clp double precision,
    budget_max_clp double precision,
    provider_match_status text not null default 'pendiente_revision_manual',
    photo_paths jsonb not null default '[]'::jsonb,
    -- Etiquetas de resultado real para futura validación/aprendizaje supervisado.
    actual_debris_volume_m3 double precision,
    actual_person_hours double precision,
    actual_final_cost_clp double precision,
    actual_cleaning_level text,
    actual_completion_date date,
    outcome_verified boolean not null default false
);

alter table public.georiskai_requests enable row level security;
revoke all on public.georiskai_requests from anon, authenticated;
grant insert on public.georiskai_requests to anon;

drop policy if exists "anon_insert_georiskai_requests" on public.georiskai_requests;
create policy "anon_insert_georiskai_requests"
on public.georiskai_requests
for insert to anon
with check (true);

create table if not exists public.georiskai_insurance_requests (
    id uuid primary key,
    created_at timestamptz not null default now(),
    comuna text not null,
    risks jsonb not null default '[]'::jsonb,
    purpose text not null,
    active_policy_status text,
    contact_name text,
    email text,
    phone text,
    consent_contact_sharing boolean not null default false,
    matched_partner_names jsonb not null default '[]'::jsonb,
    match_status text not null
);

alter table public.georiskai_insurance_requests enable row level security;
revoke all on public.georiskai_insurance_requests from anon, authenticated;
grant insert on public.georiskai_insurance_requests to anon;

drop policy if exists "anon_insert_georiskai_insurance_requests" on public.georiskai_insurance_requests;
create policy "anon_insert_georiskai_insurance_requests"
on public.georiskai_insurance_requests
for insert to anon
with check (true);

-- Bucket privado. Las fotos solo se conservan cuando la persona autoriza
-- expresamente su uso para mejora del modelo.
insert into storage.buckets (id, name, public)
values ('georiskai-photos', 'georiskai-photos', false)
on conflict (id) do nothing;

drop policy if exists "anon_upload_georiskai_training_photos" on storage.objects;
create policy "anon_upload_georiskai_training_photos"
on storage.objects
for insert to anon
with check (bucket_id = 'georiskai-photos');
