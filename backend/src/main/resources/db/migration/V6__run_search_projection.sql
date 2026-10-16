-- Current-version search values. Immutable original summaries remain authoritative.
ALTER TABLE run ADD COLUMN pressure_mtorr double precision,
    ADD COLUMN source_power_w double precision,
    ADD COLUMN bias_power_w double precision,
    ADD COLUMN mean_ion_energy_ev double precision,
    ADD COLUMN ion_flux_1e18 double precision,
    ADD COLUMN ied_width_ev double precision,
    ADD COLUMN searchable boolean NOT NULL DEFAULT false,
    ADD COLUMN search_projection_version integer;
ALTER TABLE run_version ADD COLUMN source_file_count integer CHECK (source_file_count >= 0);

CREATE FUNCTION run_search_watt_v1(unit text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE written text; expected text := '오ᅡ트'; shorter text; longer text; differences integer := 0; i integer;
BEGIN
    IF lower(unit) IN ('w','와트','watt','watts') THEN RETURN true; END IF;
    IF unit !~ '^[가-힣ㄱ-ㅣᄀ-ᇿ]+$' THEN RETURN false; END IF;
    written := replace(normalize(unit, NFKD), 'ᅪ', 'ᅩᅡ');
    IF abs(length(written)-length(expected)) > 1 THEN RETURN false; END IF;
    IF length(written)=length(expected) THEN
        FOR i IN 1..length(expected) LOOP
            IF substr(written,i,1)<>substr(expected,i,1) THEN differences:=differences+1; END IF;
        END LOOP;
        RETURN differences<=1;
    END IF;
    IF length(written)<length(expected) THEN shorter:=written;longer:=expected;
    ELSE shorter:=expected;longer:=written; END IF;
    FOR i IN 1..length(shorter) LOOP
        IF substr(shorter,i,1)<>substr(longer,i,1) THEN RETURN substr(shorter,i)=substr(longer,i+1); END IF;
    END LOOP;
    RETURN true;
END $$;

CREATE FUNCTION run_search_scalar_v1(summary jsonb, metric text) RETURNS double precision
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE raw jsonb; unit text; name text; canonical text; value double precision;
    whitespace text := U&'\0009-\000D\001C-\0020\0085\00A0\1680\2000-\200A\2028\2029\202F\205F\3000';
BEGIN
    canonical := CASE metric WHEN 'pressure' THEN 'mTorr' WHEN 'sourcePower' THEN 'W' WHEN 'biasPower' THEN 'W'
        WHEN 'meanIonEnergy' THEN 'eV' WHEN 'iedWidth' THEN 'eV' WHEN 'ionFlux' THEN '10¹⁸ m⁻²s⁻¹' END;
    IF canonical IS NULL THEN RETURN NULL; END IF;
    raw := CASE WHEN metric IN ('meanIonEnergy','ionFlux','iedWidth') THEN summary->'metrics'->metric ELSE summary->metric END;
    IF jsonb_typeof(raw) IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
    BEGIN
        value := (raw::text)::double precision;
    EXCEPTION WHEN numeric_value_out_of_range THEN
        -- PostgreSQL throws on a rounded-to-zero underflow; Python binary64 returns zero.
        IF abs((raw::text)::numeric) < 4.9406564584124654e-324::numeric THEN value:=0;
        ELSE RETURN NULL; END IF;
    END;
    unit := regexp_replace(coalesce(summary->'units'->>metric,canonical),'^['||whitespace||']+|['||whitespace||']+$','','g');
    name := lower(regexp_replace(unit,'['||whitespace||']','','g'));
    IF metric IN ('sourcePower','biasPower') AND run_search_watt_v1(unit) THEN unit:='W'; END IF;
    IF metric IN ('meanIonEnergy','iedWidth') AND name IN ('ev','e볼트','이볼트','전자볼트','일렉트론볼트','electronvolt','electronvolts') THEN unit:='eV'; END IF;
    IF metric='pressure' THEN
        IF name IN ('mtorr','밀리토르','밀리토어','millitorr') THEN unit:='mTorr';
        ELSIF name IN ('torr','토르','토어') THEN unit:='Torr'; END IF;
    END IF;
    BEGIN
        IF unit=canonical THEN NULL;
        ELSIF metric='pressure' AND unit='Torr' THEN value:=value*1000::double precision;
        ELSIF metric='ionFlux' AND unit IN ('m⁻²s⁻¹','m^-2s^-1','m^-2 s^-1','m-2s-1') THEN value:=value/1e18::double precision;
        ELSIF metric='ionFlux' AND unit IN ('10^18 m^-2s^-1','10^18 m^-2 s^-1') THEN NULL;
        ELSE RETURN NULL; END IF;
    EXCEPTION WHEN numeric_value_out_of_range THEN
        IF metric='ionFlux' AND abs(value)<4.9406564584124654e-306::double precision THEN RETURN 0;
        ELSE RETURN NULL; END IF;
    END;
    IF value IN ('Infinity'::double precision,'-Infinity'::double precision,'NaN'::double precision) THEN RETURN NULL; END IF;
    RETURN CASE WHEN value=0 THEN 0 ELSE value END;
END $$;

-- One canonical update routine is shared by registration, backfill and test fixtures.
CREATE FUNCTION run_search_refresh_v1(target_run_id text) RETURNS void
LANGUAGE sql AS $$
    UPDATE run r SET
        pressure_mtorr=run_search_scalar_v1(v.summary,'pressure'),
        source_power_w=run_search_scalar_v1(v.summary,'sourcePower'),
        bias_power_w=run_search_scalar_v1(v.summary,'biasPower'),
        mean_ion_energy_ev=run_search_scalar_v1(v.summary,'meanIonEnergy'),
        ion_flux_1e18=run_search_scalar_v1(v.summary,'ionFlux'),
        ied_width_ev=run_search_scalar_v1(v.summary,'iedWidth'),
        searchable=coalesce(v.summary->>'qualityStatus'='VERIFIED' AND v.summary->>'convergenceStatus'='CONVERGED' AND v.summary->>'catalogStatus'='READY',false),
        search_projection_version=1
    FROM run_version v WHERE v.id=r.current_version_id AND r.run_id=target_run_id;
$$;

UPDATE run_version SET source_file_count=CASE WHEN jsonb_typeof(full_run->'sourceFiles')='array' THEN jsonb_array_length(full_run->'sourceFiles') END;
UPDATE run r SET
        pressure_mtorr=run_search_scalar_v1(v.summary,'pressure'),
        source_power_w=run_search_scalar_v1(v.summary,'sourcePower'),
        bias_power_w=run_search_scalar_v1(v.summary,'biasPower'),
        mean_ion_energy_ev=run_search_scalar_v1(v.summary,'meanIonEnergy'),
        ion_flux_1e18=run_search_scalar_v1(v.summary,'ionFlux'),
        ied_width_ev=run_search_scalar_v1(v.summary,'iedWidth'),
        searchable=coalesce(v.summary->>'qualityStatus'='VERIFIED' AND v.summary->>'convergenceStatus'='CONVERGED' AND v.summary->>'catalogStatus'='READY',false),
        search_projection_version=1
    FROM run_version v WHERE v.id=r.current_version_id;
