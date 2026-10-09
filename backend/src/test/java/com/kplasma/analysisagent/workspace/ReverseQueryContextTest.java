package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class ReverseQueryContextTest extends WorkspaceTestSupport {
    private String path;
    private Map<String,Object> fence;
    private HttpResponse<String> internal(String suffix, Object body) throws Exception {
        return HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+suffix))
            .header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    private void start() throws Exception {
        var request=ok("POST","/api/agent/requests",Map.of("text","인공 역방향 조건 조회","stateToken",token()),UUID.randomUUID().toString());
        path="/requests/"+request.get("requestId").stringValue();
        var claimed=json(internal("/claim",Map.of("workerId","reverse-test","leaseSeconds",60)));
        fence=Map.of("claimGeneration",claimed.get("claimGeneration").longValue(),"requestRevision",claimed.get("requestRevision").longValue());
    }
    private Map<String,Object> body(Map<String,Object> fields) {var body=new HashMap<String,Object>(fence);body.putAll(fields);return body;}
    private JsonNode context(Map<String,Object> fields) throws Exception {
        var response=internal(path+"/context",body(fields));assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);
    }
    private Map<String,Object> constraint(String metric,String operator,double value) {return Map.of("metric",metric,"operator",operator,"value",value,"unit",metric.equals("pressure")?"mTorr":"eV");}
    private Map<String,Object> range(double min,double max) {return Map.of("metric","meanIonEnergy","operator","between","min",min,"max",max,"unit","eV");}
    private Map<String,Object> goal(String metric,String direction) {return Map.of("metric",metric,"direction",direction,"unit",metric.equals("ionFlux")?"10¹⁸ m⁻²s⁻¹":"eV");}
    private Map<String,Object> query(List<Map<String,Object>> constraints,List<Map<String,Object>> goals) {return Map.of("constraints",constraints,"goals",goals);}
    private void metric(int index,String name,Double value) {jdbc.update("update run_version set summary=jsonb_set(summary,?::text[],?::jsonb) where id=?",new String[]{"metrics",name},mapper.writeValueAsString(value),UUID.fromString(refs.get(index).get("runVersionId").stringValue()));}
    private List<String> ids(JsonNode manifest) {List<String> result=new ArrayList<>();manifest.get("runs").forEach(run->result.add(run.get("runId").stringValue()));return result;}

    @Test void filtersMatchingCandidatesAndOrdersFluxWithoutFetchingGlobalRankList() throws Exception {
        metric(0,"meanIonEnergy",155.0);metric(1,"meanIonEnergy",156.0);metric(2,"meanIonEnergy",20.0);metric(3,"meanIonEnergy",200.0);
        metric(0,"ionFlux",10.0);metric(1,"ionFlux",30.0);metric(2,"ionFlux",1000.0);
        start();var q=query(List.of(range(150,160)),List.of(goal("ionFlux","maximize")));
        var manifest=context(Map.of("reverseQuery",q));
        assertThat(ids(manifest)).containsExactly("SYNTHETIC-1","SYNTHETIC-0");
        assertThat(manifest.get("catalogRunRefs").size()).isEqualTo(4);
        assertThat(manifest.get("reverseQuery")).isEqualTo(mapper.valueToTree(q));
        assertThat(manifest.get("runs").get(0).has("sourceFiles")).isFalse();
    }
    @Test void retainsIndependentConditionMatchesAndUnavailableRecordsForReasons() throws Exception {
        metric(0,"meanIonEnergy",155.0);metric(1,"meanIonEnergy",156.0);metric(2,"meanIonEnergy",20.0);metric(3,"meanIonEnergy",200.0);
        metric(0,"iedWidth",1.0);metric(1,"iedWidth",8.0);metric(2,"iedWidth",2.0);metric(3,"ionFlux",null);
        start();var manifest=context(Map.of("reverseQuery",query(List.of(range(150,160),constraint("iedWidth","lte",3)),List.of(goal("ionFlux","maximize")))));
        assertThat(ids(manifest)).containsExactlyInAnyOrder("SYNTHETIC-0","SYNTHETIC-1","SYNTHETIC-2","SYNTHETIC-3");
        assertThat(manifest.get("runs").size()).isEqualTo(4);
        for(var run:manifest.get("runs"))if(run.get("runId").stringValue().equals("SYNTHETIC-3"))assertThat(run.get("metrics").get("ionFlux").isNull()).isTrue();
    }
    @Test void strictBinary64BoundaryFilteringAndOrderedGoalPrecedenceArePreserved() throws Exception {
        metric(0,"meanIonEnergy",150.0);metric(1,"meanIonEnergy",Math.nextUp(150.0));metric(2,"meanIonEnergy",160.0);metric(3,"meanIonEnergy",149.0);
        metric(0,"ionFlux",1000.0);metric(1,"ionFlux",20.0);metric(2,"ionFlux",20.0);metric(1,"iedWidth",5.0);metric(2,"iedWidth",2.0);
        start();var manifest=context(Map.of("reverseQuery",query(List.of(constraint("meanIonEnergy","gt",150)),List.of(goal("ionFlux","maximize"),goal("iedWidth","minimize")))));
        assertThat(ids(manifest)).containsExactly("SYNTHETIC-2","SYNTHETIC-1");
    }
    @Test void softTargetRangeOrdersInsideBeforeClosestOutsideWithoutFilteringIt() throws Exception {
        metric(0,"meanIonEnergy",100.0);metric(1,"meanIonEnergy",155.0);metric(2,"meanIonEnergy",170.0);metric(3,"meanIonEnergy",153.0);
        start();var soft=Map.<String,Object>of("metric","meanIonEnergy","direction","target_range","min",150,"max",160,"unit","eV");
        assertThat(ids(context(Map.of("reverseQuery",query(List.of(),List.of(soft)))))).containsExactly("SYNTHETIC-1","SYNTHETIC-3","SYNTHETIC-2","SYNTHETIC-0");
    }
    @Test void sourceUnitConversionsUseSameFloat64BoundaryAsWorker() throws Exception {
        metric(0,"meanIonEnergy",155.0);metric(1,"meanIonEnergy",155.0);metric(2,"meanIonEnergy",20.0);metric(3,"meanIonEnergy",200.0);
        metric(0,"ionFlux",3e19);metric(1,"ionFlux",20.0);
        jdbc.update("update run_version set summary=jsonb_set(summary,'{units,ionFlux}',to_jsonb('m^-2 s^-1'::text)) where id=?",UUID.fromString(refs.getFirst().get("runVersionId").stringValue()));
        start();assertThat(ids(context(Map.of("reverseQuery",query(List.of(range(150,160)),List.of(goal("ionFlux","maximize"))))))).containsExactly("SYNTHETIC-0","SYNTHETIC-1");
    }
    @Test void pressureConversionRetainsOverflowAndInvalidUnitsForWorkerExclusionReasons() throws Exception {
        jdbc.update("update run_version set summary=jsonb_set(jsonb_set(summary,'{pressure}','0.003'::jsonb),'{units,pressure}',to_jsonb('Torr'::text)) where id=?",UUID.fromString(refs.getFirst().get("runVersionId").stringValue()));
        jdbc.update("update run_version set summary=jsonb_set(summary,'{pressure}','4'::jsonb) where id=?",UUID.fromString(refs.get(1).get("runVersionId").stringValue()));
        jdbc.update("update run_version set summary=jsonb_set(jsonb_set(summary,'{pressure}','1e308'::jsonb),'{units,pressure}',to_jsonb('Torr'::text)) where id=?",UUID.fromString(refs.get(2).get("runVersionId").stringValue()));
        jdbc.update("update run_version set summary=jsonb_set(summary,'{units,pressure}',to_jsonb('Pa'::text)) where id=?",UUID.fromString(refs.get(3).get("runVersionId").stringValue()));
        start();assertThat(ids(context(Map.of("reverseQuery",query(List.of(constraint("pressure","eq",3)),List.of()))))).containsExactly("SYNTHETIC-0","SYNTHETIC-2","SYNTHETIC-3");
    }
    @Test void preservesUnusableRunsAndNullVersusZeroWithDefaultContextToo() throws Exception {
        metric(0,"meanIonEnergy",155.0);metric(1,"meanIonEnergy",20.0);metric(2,"meanIonEnergy",20.0);metric(3,"meanIonEnergy",200.0);
        jdbc.update("update run_version set summary=jsonb_set(summary,'{qualityStatus}',to_jsonb('UNVERIFIED'::text)) where id=?",UUID.fromString(refs.get(1).get("runVersionId").stringValue()));
        metric(2,"ionFlux",null);metric(3,"ionFlux",0.0);
        start();var selected=context(Map.of("reverseQuery",query(List.of(range(150,160)),List.of(goal("ionFlux","maximize")))));
        assertThat(ids(selected)).containsExactlyInAnyOrder("SYNTHETIC-0","SYNTHETIC-1","SYNTHETIC-2");
        ok("POST","/api/agent"+path+"/cancel",Map.of(),null);start();var all=context(Map.of());
        assertThat(all.get("runs").get(2).get("metrics").get("ionFlux").isNull()).isTrue();
        assertThat(all.get("runs").get(3).get("metrics").get("ionFlux").doubleValue()).isZero();
    }
    @Test void extremeSoftRangeDistanceDoesNotOverflowBeforeWorkerVerification() throws Exception {
        metric(0,"meanIonEnergy",1e308);metric(1,"meanIonEnergy",0.0);metric(2,"meanIonEnergy",1.6e308);metric(3,"meanIonEnergy",1.7e308);
        start();var soft=Map.<String,Object>of("metric","meanIonEnergy","direction","target_range","min",-1.7e308,"max",-1.6e308,"unit","eV");
        assertThat(ids(context(Map.of("reverseQuery",query(List.of(),List.of(soft)))))).containsExactly("SYNTHETIC-1","SYNTHETIC-0","SYNTHETIC-2","SYNTHETIC-3");
    }
    @Test void defaultContextCanMaterializeReferenceOnlyInventoryWithoutUsingNewLatestVersions() throws Exception {
        start();var before=context(Map.of("referencesOnly",true));assertThat(before.get("runs").size()).isZero();
        jdbc.update("update run set current_version_id=null where run_id='SYNTHETIC-3'");
        assertThat(context(Map.of()).get("runs").size()).isEqualTo(4);
    }
    @Test void referenceOnlyPinsCatalogBeforeQueryAndRepeatedQueryDoesNotRefreshVersions() throws Exception {
        metric(0,"meanIonEnergy",155.0);metric(1,"meanIonEnergy",20.0);metric(2,"meanIonEnergy",20.0);metric(3,"meanIonEnergy",200.0);
        start();var before=context(Map.of("referencesOnly",true,"requiredRunRefs",List.of(refs.getFirst())));
        assertThat(before.get("runs").size()).isZero();assertThat(before.get("referencedRuns").size()).isEqualTo(1);assertThat(before.get("catalogRunRefs").size()).isEqualTo(4);
        UUID newer=UUID.randomUUID();String old=refs.getFirst().get("runVersionId").stringValue();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),jsonb_set(jsonb_set(summary,'{runVersionId}',to_jsonb(?::text)),'{metrics,meanIonEnergy}','20'::jsonb),jsonb_set(full_run,'{runVersionId}',to_jsonb(?::text)) from run_version where id=?",newer,newer.toString(),newer.toString(),UUID.fromString(old));
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'",newer);
        var q=query(List.of(range(150,160)),List.of(goal("ionFlux","maximize")));var selected=context(Map.of("reverseQuery",q));
        assertThat(ids(selected)).containsExactly("SYNTHETIC-0");assertThat(selected.get("runs").get(0).get("runVersionId").stringValue()).isEqualTo(old);
        assertThat(context(Map.of("reverseQuery",q))).isEqualTo(selected);
        jdbc.update("update agent_request set lease_until=now()-interval '1 second' where id=?",UUID.fromString(path.substring("/requests/".length())));
        var reclaimed=json(internal("/claim",Map.of("workerId","restarted-worker","leaseSeconds",60)));
        fence=Map.of("claimGeneration",reclaimed.get("claimGeneration").longValue(),"requestRevision",reclaimed.get("requestRevision").longValue());
        assertThat(context(Map.of("reverseQuery",q))).isEqualTo(selected);
        var changed=internal(path+"/context",body(Map.of("reverseQuery",query(List.of(range(1,30)),List.of()))));assertThat(changed.statusCode()).isEqualTo(409);
        var augmented=context(Map.of("reverseQuery",q,"requiredRunRefs",List.of(Map.of("runId","SYNTHETIC-0","runVersionId",newer.toString()))));
        assertThat(augmented.get("runs")).isEqualTo(selected.get("runs"));assertThat(augmented.get("referencedRuns").size()).isEqualTo(2);
    }
    @Test void noCommonMatchKeepsPinnedPoolForExistingNearMatchPolicy() throws Exception {
        metric(0,"ionFlux",1.0);metric(1,"ionFlux",1000.0);
        start();assertThat(ids(context(Map.of("reverseQuery",query(List.of(range(150,160)),List.of(goal("ionFlux","maximize"))))))).containsExactly("SYNTHETIC-0","SYNTHETIC-1","SYNTHETIC-2","SYNTHETIC-3");
    }
    @Test void tinySourceNumbersDoNotThrowOrDisappearBeforeWorkerNormalization() throws Exception {
        jdbc.update("update run_version set summary=jsonb_set(summary,'{metrics,meanIonEnergy}','1e-330'::jsonb) where id=?",UUID.fromString(refs.getFirst().get("runVersionId").stringValue()));
        metric(1,"meanIonEnergy",0.0);
        start();assertThat(ids(context(Map.of("reverseQuery",query(List.of(constraint("meanIonEnergy","eq",0)),List.of(goal("ionFlux","maximize"))))))).containsExactly("SYNTHETIC-0","SYNTHETIC-1");
    }
    @Test void rawFluxUnitConversionUnderflowKeepsZeroCandidatesForWorkerNormalization() throws Exception {
        metric(0,"ionFlux",1e-308);metric(1,"ionFlux",0.0);
        jdbc.update("update run_version set summary=jsonb_set(summary,'{units,ionFlux}',to_jsonb('m^-2 s^-1'::text)) where id=?",UUID.fromString(refs.getFirst().get("runVersionId").stringValue()));
        start();var flux=Map.<String,Object>of("metric","ionFlux","operator","eq","value",0,"unit","10¹⁸ m⁻²s⁻¹");
        assertThat(ids(context(Map.of("reverseQuery",query(List.of(flux),List.of()))))).containsExactly("SYNTHETIC-0","SYNTHETIC-1");
    }
    @Test void rejectsUnknownMetricInvalidBoundsUnitsAndConflictingModes() throws Exception {
        start();
        var invalids=List.of(
            query(List.of(constraint("notAColumn","eq",1)),List.of()),
            query(List.of(range(160,150)),List.of()),
            query(List.of(Map.of("metric","meanIonEnergy","operator","eq","value",1,"unit","keV")),List.of()),
            query(List.of(Map.of("metric","meanIonEnergy","operator","eq","value","1","unit","eV")),List.of()),
            query(List.of(),List.of(goal("pressure","maximize"))),query(List.of(),List.of()));
        for(var q:invalids)assertThat(internal(path+"/context",body(Map.of("reverseQuery",q))).statusCode()).isEqualTo(400);
        assertThat(internal(path+"/context",body(Map.of("reverseQuery",query(List.of(),List.of()),"referencesOnly",true))).statusCode()).isEqualTo(400);
    }
}
