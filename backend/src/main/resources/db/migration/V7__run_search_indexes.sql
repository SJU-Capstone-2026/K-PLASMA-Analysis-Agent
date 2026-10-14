CREATE INDEX run_search_energy_idx ON run USING btree (mean_ion_energy_ev)
    WHERE searchable AND mean_ion_energy_ev IS NOT NULL;
CREATE INDEX run_search_flux_idx ON run USING btree (ion_flux_1e18)
    WHERE searchable AND ion_flux_1e18 IS NOT NULL;
CREATE INDEX run_search_width_idx ON run USING btree (ied_width_ev)
    WHERE searchable AND ied_width_ev IS NOT NULL;
CREATE INDEX run_search_conditions_idx ON run USING btree (pressure_mtorr,source_power_w,bias_power_w)
    WHERE searchable;
ANALYZE run;
