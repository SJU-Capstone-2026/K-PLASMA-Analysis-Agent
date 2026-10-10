SELECT v.summary::text, jsonb_array_length(v.full_run->'sourceFiles')
FROM run r JOIN run_version v ON v.id = r.current_version_id
WHERE r.run_id = 'RUN-P' || lpad(cast(:pressure AS text),2,'0')
             || '-S' || lpad(cast(:source AS text),3,'0')
             || '-B' || lpad(cast(:bias AS text),4,'0')
ORDER BY r.run_id, v.registration_sequence;
