package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.ingestion.IntakeException;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.ObjectMapper;

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
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) values (?,?,?,?,?::jsonb,?::jsonb)",id,full.runId(),source,java.sql.Timestamp.from(Instant.parse(full.registeredAt())),mapper.writeValueAsString(summary),mapper.writeValueAsString(full));
        jdbc.update("update run set current_version_id=? where run_id=?",id,full.runId());
    }
    public List<RunDto.Summary> searchable() {
        return jdbc.query("select v.summary from run r join run_version v on v.id=r.current_version_id order by r.run_id",(rs,n)->mapper.readValue(rs.getString(1),RunDto.Summary.class));
    }
    public RunDto.Full version(UUID id) {
        var versions=jdbc.query("select full_run from run_version where id=?",(rs,n)->mapper.readValue(rs.getString(1),RunDto.Full.class),id);
        if(versions.isEmpty()) throw new IntakeException("NOT_FOUND",404,"Run version not found");
        return versions.getFirst();
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
