insert into public.tours (slug, display_name, governing_body, gender)
values
    ('atp', 'ATP Tour', 'ATP', 'men'),
    ('wta', 'WTA Tour', 'WTA', 'women')
on conflict (slug) do update
set display_name = excluded.display_name,
    governing_body = excluded.governing_body,
    gender = excluded.gender,
    updated_at = timezone('utc', now());

insert into public.surfaces (slug, display_name, pace_class)
values
    ('hard', 'Hard Court', 'medium'),
    ('clay', 'Clay Court', 'slow'),
    ('grass', 'Grass Court', 'fast'),
    ('carpet', 'Carpet', 'fast')
on conflict (slug) do update
set display_name = excluded.display_name,
    pace_class = excluded.pace_class,
    updated_at = timezone('utc', now());
