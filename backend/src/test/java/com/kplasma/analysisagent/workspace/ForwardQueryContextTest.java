package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class ForwardQueryContextTest extends WorkspaceTestSupport {
    private String path;
    private Map<String,Object> fence;
    private static final String ID="RUN-P08-S300-B0600";
    private static final Map<String,Object> QUERY=Map.of("pressure",8,"sourcePower",300,"biasPower",600);

    private HttpResponse<String> internal(String suffix,Object body) throws Exception {
        return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+suffix))
            .header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    private Map<String,Object> body(Map<String,Object> fields) {var body=new HashMap<String,Object>(fence);body.putAll(fields);return body;}
    private JsonNode context(Map<String,Object> fields) throws Exception {
        var response=internal(path+"/context",body(fields));assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);
    }
    private void start() throws Exception {
        var request=ok("POST","/api/agent/requests",Map.of("text","인공 순방향 조회","stateToken",token()),UUID.randomUUID().toString());
        path="/requests/"+request.get("requestId").stringValue();
        var claim=json(internal("/claim",Map.of("workerId","forward-test","leaseSeconds",60)));
        fence=Map.of("claimGeneration",claim.get("claimGeneration").longValue(),"requestRevision",claim.get("requestRevision").longValue());
        assertThat(internal(path+"/heartbeat",body(Map.of("stage","gather","operationKind","forward_lookup"))).statusCode()).isEqualTo(200);
    }
    private UUID canonical(double pressure,String quality) {
        UUID version=UUID.randomUUID();
        jdbc.update("insert into run(run_id) values (?) on conflict do nothing",ID);
        var summary=mapper.createObjectNode().put("runId",ID).put("runVersionId",version.toString())
            .put("pressure",pressure).put("sourcePower",300).put("biasPower",600)
            .put("qualityStatus",quality).put("catalogStatus","READY").put("convergenceStatus","CONVERGED");
        summary.set("units",mapper.valueToTree(Map.of("pressure","mTorr","sourcePower","W","biasPower","W")));
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,?,source_id,now(),?::jsonb,full_run from run_version where id=?",version,ID,summary.toString(),UUID.fromString(refs.getFirst().get("runVersionId").stringValue()));
        jdbc.update("update run set current_version_id=? where run_id=?",version,ID);return version;
    }

    @Test void exactLookupPinsOnlyTheMatchAndReplaysItsImmutableVersion() throws Exception {
        var original=canonical(8,"VERIFIED");start();
        var first=context(Map.of("forwardQuery",QUERY));
        assertThat(first.get("runs").size()).isEqualTo(1);
        assertThat(first.get("catalogRunRefs").size()).isEqualTo(1);
        assertThat(first.get("runs").get(0).get("runVersionId").stringValue()).isEqualTo(original.toString());
        canonical(8,"VERIFIED");
        assertThat(context(Map.of("forwardQuery",QUERY))).isEqualTo(first);
        var extended=context(Map.of("requiredRunRefs",List.of(refs.getFirst()),"referencesOnly",true));
        assertThat(extended.get("referencedRuns").size()).isEqualTo(1);
        assertThat(extended.get("runs")).isEqualTo(first.get("runs"));
        assertThat(internal(path+"/context",body(Map.of("forwardQuery",Map.of("pressure",10,"sourcePower",300,"biasPower",600)))).statusCode()).isEqualTo(409);
    }
    @Test void referencePreparationDoesNotPinTheEntireCatalog() throws Exception {
        canonical(8,"VERIFIED");start();
        var prepared=context(Map.of("referencesOnly",true,"requiredRunRefs",List.of(refs.getFirst())));
        assertThat(prepared.get("runs").size()).isZero();
        assertThat(prepared.get("catalogRunRefs").size()).isZero();
        assertThat(prepared.get("referencedRuns").size()).isEqualTo(1);
        assertThat(context(Map.of("forwardQuery",QUERY)).get("runs").size()).isEqualTo(1);
    }
    @Test void missingOrNonRepresentableKeyKeepsLegacyNearestPool() throws Exception {
        start();
        var result=context(Map.of("forwardQuery",Map.of("pressure",8.5,"sourcePower",300,"biasPower",600)));
        assertThat(result.get("runs").size()).isEqualTo(4);
        assertThat(result.get("catalogRunRefs").size()).isEqualTo(4);
    }
    @Test void roundedIdCannotMakeDifferentConditionsAnExactMatch() throws Exception {
        canonical(8.5,"VERIFIED");start();
        assertThat(context(Map.of("forwardQuery",QUERY)).get("runs").size()).isEqualTo(5);
    }
    @Test void unavailableExactRunKeepsExclusionsAndNearestPool() throws Exception {
        canonical(8,"REJECTED");start();
        assertThat(context(Map.of("forwardQuery",QUERY)).get("runs").size()).isEqualTo(5);
    }
    @Test void rejectsMalformedOrMixedQueryBeforePinning() throws Exception {
        start();
        assertThat(internal(path+"/context",body(Map.of("forwardQuery",Map.of("pressure","8")))).statusCode()).isEqualTo(400);
        assertThat(internal(path+"/context",body(Map.of("forwardQuery",QUERY,"referencesOnly",true))).statusCode()).isEqualTo(400);
        assertThat(internal(path+"/context",body(Map.of("referencesOnly",true,"reverseQuery",Map.of()))).statusCode()).isEqualTo(400);
    }
    @Test void referencePreparationCanFallBackWithoutLosingTheNearestPool() throws Exception {
        start();context(Map.of("referencesOnly",true));
        var result=context(Map.of("forwardQuery",QUERY));
        assertThat(result.get("runs").size()).isEqualTo(4);
        assertThat(context(Map.of("forwardQuery",QUERY))).isEqualTo(result);
    }
    @Test void existingFullManifestIsNeverReplacedByAQueryOfNewerVersions() throws Exception {
        var original=canonical(8,"VERIFIED");start();
        var existing=context(Map.of());
        canonical(8,"VERIFIED");
        assertThat(context(Map.of("forwardQuery",QUERY))).isEqualTo(existing);
        assertThat(existing.toString()).contains(original.toString());
    }
}
