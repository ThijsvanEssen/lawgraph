-- The check of #390: the motions with text, and how many of them have a dictum. Read only.
SELECT count(*) FILTER (WHERE props -> 'dictum' IS NOT NULL) AS with_dictum, count(*) AS motions_with_text FROM documents WHERE starts_with(kind, 'Motie') AND coalesce(json_typeof(props -> 'text'), 'null') = 'string';
