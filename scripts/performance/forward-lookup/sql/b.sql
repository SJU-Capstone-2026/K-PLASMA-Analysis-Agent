SELECT v.summary::text, jsonb_array_length(v.full_run->'sourceFiles')
FROM run r JOIN run_version v ON v.id = r.current_version_id
WHERE (CASE coalesce(v.summary->'units'->>'pressure','mTorr')
         WHEN 'mTorr' THEN (v.summary->>'pressure')::float8
         WHEN 'Torr' THEN (v.summary->>'pressure')::float8 * 1000 END) = :pressure
  AND coalesce(v.summary->'units'->>'sourcePower','W') = 'W'
  AND (v.summary->>'sourcePower')::float8 = :source
  AND coalesce(v.summary->'units'->>'biasPower','W') = 'W'
  AND (v.summary->>'biasPower')::float8 = :bias
ORDER BY r.run_id, v.registration_sequence;
