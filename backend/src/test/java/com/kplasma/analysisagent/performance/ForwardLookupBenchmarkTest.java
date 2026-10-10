package com.kplasma.analysisagent.performance;

import com.kplasma.analysisagent.workspace.WorkspaceTestSupport;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import static org.assertj.core.api.Assertions.*;

class ForwardLookupBenchmarkTest extends WorkspaceTestSupport {
    @Test void strategiesReturnSameCurrentVersionAndNoDuplicateConditions() throws Exception {
        for (int i=0;i<4;i++) {
            String old="SYNTHETIC-"+i, name=String.format(Locale.ROOT,"RUN-P03-S011-B%04d",i);
            jdbc.update("insert into run(run_id,current_version_id) select ?,current_version_id from run where run_id=?",name,old);
            jdbc.update("update run_version set run_id=?,summary=jsonb_set(jsonb_set(summary,'{runId}',to_jsonb(?::text)),'{biasPower}',to_jsonb(?::int)) where run_id=?",name,name,i,old);
            jdbc.update("update run_version set full_run=full_run||jsonb_build_object('runId',?::text,'biasPower',?::int) where run_id=?",name,i,name);
            jdbc.update("delete from run where run_id=?",old);
        }
        var endpoint=new ForwardLookupBenchmarkSupport.Endpoint(new NamedParameterJdbcTemplate(jdbc),mapper);
        var a=mapper.readTree(endpoint.lookup("a",3,11,0).getBody()).get("runs");
        var b=mapper.readTree(endpoint.lookup("b",3,11,0).getBody()).get("runs");
        var c=mapper.readTree(endpoint.lookup("c",3,11,0).getBody()).get("runs");
        assertThat(a.size()).isEqualTo(4);
        assertThat(b.size()).isEqualTo(1);
        assertThat(b).isEqualTo(c);
        assertThat(b.get(0)).isEqualTo(a.get(0));
        assertThat(b.get(0).get("runVersionId").stringValue()).isEqualTo(refs.get(0).get("runVersionId").stringValue());
        assertThat(mapper.readTree(endpoint.lookup("c",3,11,10).getBody()).get("runs").size()).isZero();
        assertThat(mapper.readTree(endpoint.lookup("b",3,11,10).getBody()).get("runs").size()).isZero();
        assertThat(endpoint.lookup("other",3,11,0).getStatusCode().value()).isEqualTo(400);
        // Updating one condition's current version must not add a second current Run.
        UUID next=UUID.randomUUID();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),jsonb_set(summary,'{runVersionId}',to_jsonb(?::text)),jsonb_set(full_run,'{runVersionId}',to_jsonb(?::text)) from run_version where id=?::uuid",
            next,next.toString(),next.toString(),refs.get(0).get("runVersionId").stringValue());
        jdbc.update("update run set current_version_id=? where run_id='RUN-P03-S011-B0000'",next);
        var updated=mapper.readTree(endpoint.lookup("c",3,11,0).getBody()).get("runs");
        assertThat(updated.size()).isEqualTo(1);
        assertThat(updated.get(0).get("runVersionId").stringValue()).isEqualTo(next.toString());
        assertThat(jdbc.queryForObject("select count(*) from run",Integer.class)).isEqualTo(4);
        assertThat(jdbc.queryForObject("select count(*) from run_version",Integer.class)).isEqualTo(5);
        // Both lookup paths preserve the stored unit; Python normalizes the selected summary.
        jdbc.update("update run_version set summary=jsonb_set(jsonb_set(summary,'{pressure}','0.003'::jsonb),'{units,pressure}','\"Torr\"'::jsonb) where id=?",next);
        var torrB=mapper.readTree(endpoint.lookup("b",3,11,0).getBody()).get("runs");
        var torrC=mapper.readTree(endpoint.lookup("c",3,11,0).getBody()).get("runs");
        assertThat(torrB.size()).isEqualTo(1);
        assertThat(torrB).isEqualTo(torrC);
    }
}
