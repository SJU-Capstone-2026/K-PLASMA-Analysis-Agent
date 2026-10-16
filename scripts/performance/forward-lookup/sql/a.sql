SELECT v.summary::text, jsonb_array_length(v.full_run->'sourceFiles')
FROM run r JOIN run_version v ON v.id = r.current_version_id
ORDER BY r.run_id, v.registration_sequence;
