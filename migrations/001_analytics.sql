drop view if exists analytics_docs_dashboard_integration_sessions;
drop view if exists analytics_integration_sessions;
drop table if exists analytics_identity_links;
drop table if exists analytics_session_state;

create table if not exists analytics_events (
  id bigserial primary key,
  occurred_at timestamptz not null default now(),
  install_id text not null,
  mid text,
  inferred_session_id uuid not null,
  event jsonb not null
);

create index if not exists analytics_events_install_time_idx
  on analytics_events (install_id, occurred_at desc, id desc);

create index if not exists analytics_events_mid_time_idx
  on analytics_events (mid, occurred_at desc)
  where mid is not null;

create index if not exists analytics_events_session_idx
  on analytics_events (inferred_session_id, occurred_at);

create index if not exists analytics_events_event_gin_idx
  on analytics_events using gin (event jsonb_path_ops);

create or replace view analytics_integration_sessions as
with install_identity as (
  select distinct on (install_id)
    install_id,
    mid as latest_mid
  from analytics_events
  where mid is not null
  order by install_id, occurred_at desc, id desc
),
session_identity as (
  select distinct on (install_id, inferred_session_id)
    install_id,
    inferred_session_id,
    mid as session_mid
  from analytics_events
  where mid is not null
  order by install_id, inferred_session_id, occurred_at desc, id desc
),
session_rollups as (
  select
    e.install_id,
    e.inferred_session_id,
    max(coalesce(s.session_mid, i.latest_mid)) as mid,
    min(e.occurred_at) as started_at,
    max(e.occurred_at) as ended_at,
    bool_or(e.event->>'mcp' = 'docs') as has_docs,
    bool_or(e.event->>'mcp' = 'dashboard') as has_dashboard,
    count(*) as event_count,
    count(*) filter (where e.event->>'type' = 'tool_call') as tool_call_count,
    count(*) filter (where e.event->>'type' = 'stage_status') as stage_event_count,
    max(
      case
        when e.event->>'type' = 'stage_status'
         and e.event->>'status' = 'completed'
        then case e.event->>'phase'
          when 'setup' then 1
          when 'prd' then 2
          when 'architecture' then 3
          when 'backend' then 4
          when 'frontend' then 5
          when 'validation' then 6
          when 'live' then 7
          else 0
        end
        else 0
      end
    ) as completed_phase_rank,
    coalesce(
      jsonb_agg(
        jsonb_build_object(
          'occurred_at', e.occurred_at,
          'event', e.event
        )
        order by e.occurred_at
      ) filter (where e.event->>'type' = 'stage_status'),
      '[]'::jsonb
    ) as stage_events
  from analytics_events e
  left join install_identity i on i.install_id = e.install_id
  left join session_identity s
    on s.install_id = e.install_id
   and s.inferred_session_id = e.inferred_session_id
  group by e.install_id, e.inferred_session_id
)
select
  install_id,
  inferred_session_id,
  mid,
  started_at,
  ended_at,
  has_docs,
  has_dashboard,
  event_count,
  tool_call_count,
  stage_event_count,
  case completed_phase_rank
    when 1 then 'setup'
    when 2 then 'prd'
    when 3 then 'architecture'
    when 4 then 'backend'
    when 5 then 'frontend'
    when 6 then 'validation'
    when 7 then 'live'
    else null
  end as last_completed_phase,
  stage_events
from session_rollups;

create or replace view analytics_docs_dashboard_integration_sessions as
select *
from analytics_integration_sessions
where has_docs and has_dashboard;
