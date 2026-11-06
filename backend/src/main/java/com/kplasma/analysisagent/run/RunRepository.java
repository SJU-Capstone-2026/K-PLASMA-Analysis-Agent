package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.contract.RunOutputDto.Display;
import com.kplasma.analysisagent.contract.RunOutputDto.GridRow;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.ingestion.ImportTimingRecorder;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

@Repository
public class RunRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    public RunRepository(JdbcTemplate jdbc,ObjectMapper mapper) { this.jdbc=jdbc;this.mapper=mapper; }
    public void lock(String runId) {
        jdbc.update("insert into run(run_id) values (?) on conflict do nothing",runId);
        jdbc.queryForList("select run_id from run where run_id=? for update",runId);
    }
    public void save(UUID source,RunDto.Summary summary,RunDto.Full full) {
        UUID id=UUID.fromString(full.runVersionId());
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run,source_file_count) values (?,?,?,?,?::jsonb,?::jsonb,?)",id,full.runId(),source,java.sql.Timestamp.from(Instant.parse(full.registeredAt())),ImportTimingRecorder.call("run.serialize.summary",()->mapper.writeValueAsString(summary)),ImportTimingRecorder.call("run.serialize.full",()->mapper.writeValueAsString(full)),full.sourceFiles()==null?null:full.sourceFiles().size());
        jdbc.update("update run set current_version_id=? where run_id=?",id,full.runId());
        jdbc.queryForObject("select run_search_refresh_v1(?)",Object.class,full.runId());
    }
    public List<RunDto.Summary> searchable() {
        return jdbc.query("select v.summary from run r join run_version v on v.id=r.current_version_id order by r.run_id",(rs,n)->mapper.readValue(rs.getString(1),RunDto.Summary.class));
    }
    public RunDto.Full version(UUID id) {
        var versions=jdbc.query("""
            select v.full_run, (select jsonb_object_agg(o.output_id, o.display)
                                from run_output_snapshot o where o.run_version_id=v.id) as displays
            from run_version v where v.id=?
            """,(rs,n)->{
                var full = (ObjectNode)mapper.readTree(rs.getString("full_run"));
                String displays = rs.getString("displays");
                if (displays != null) overlayGraphs(full, mapper.readTree(displays));
                return mapper.treeToValue(full, RunDto.Full.class);
            },id);
        if(versions.isEmpty()) throw new IntakeException("NOT_FOUND",404,"Run version not found");
        return versions.getFirst();
    }

    private void overlayGraphs(ObjectNode full, JsonNode displays) {
        var analysis = (ObjectNode)full.get("analysis");
        for (var entry : displays.properties()) {
            String id = entry.getKey();
            var display = mapper.treeToValue(entry.getValue(), Display.class);
            switch (id) {
                case "ied" -> full.set("iedDistribution", mapper.valueToTree(display.samples().stream()
                    .map(point -> new RunDto.IedPoint(point.x(), point.y())).toList()));
                case "iad", "residual" -> analysis.set(id.equals("iad") ? "iad" : "residualTrace",
                    mapper.valueToTree(display.samples().stream()
                        .map(point -> new RunDto.Pair(point.x(), point.y())).toList()));
                case "current", "potential" -> {
                    var samples = display.samples();
                    var points = samples.stream().map(point -> new RunDto.Pair(point.x(), point.y())).toList();
                    var range = new RunDto.Pair(samples.getFirst().x(), samples.getLast().x());
                    analysis.set(id, mapper.valueToTree(new RunDto.Waveform(points, range, points.size())));
                }
                case "iead" -> {
                    var rows = display.rows();
                    var angles = rows.stream().map(GridRow::x).toList();
                    var energies = rows.getFirst().coordinates();
                    var values = rows.stream().flatMap(row -> row.values().stream()).toList();
                    var shape = new RunDto.Pair(angles.size(), energies.size());
                    var range = new RunDto.Pair(angles.getFirst(), angles.getLast());
                    analysis.set(id, mapper.valueToTree(new RunDto.Iead(angles, energies, values, shape, range)));
                }
                case "density" -> {
                    var rows = display.rows().stream().map(row -> new RunDto.DensityRow(
                        row.x(), row.coordinates(), row.values())).toList();
                    var shape = new RunDto.Pair(rows.size(), rows.getFirst().distances().size());
                    analysis.set(id, mapper.valueToTree(new RunDto.Density(rows, shape)));
                }
            }
        }
    }
    public record CatalogRun(RunDto.Summary summary,List<RunDto.SourceFile> sourceFiles) {}
    public List<CatalogRun> catalogRuns() {
        // A single statement keeps summaries and their version-scoped presentation files consistent.
        return jdbc.query("select v.summary,v.full_run->'sourceFiles' from run r join run_version v on v.id=r.current_version_id order by r.run_id",(rs,n)->
            new CatalogRun(mapper.readValue(rs.getString(1),RunDto.Summary.class),mapper.readValue(rs.getString(2),new tools.jackson.core.type.TypeReference<List<RunDto.SourceFile>>(){})));
    }
    public RunDto.RunRef sourceVersion(UUID source) {
        var refs=jdbc.query("select run_id,id from run_version where source_id=? order by registration_sequence desc limit 1",(rs,n)->new RunDto.RunRef(rs.getString(1),rs.getString(2)),source);
        return refs.isEmpty()?null:refs.getFirst();
    }
}
