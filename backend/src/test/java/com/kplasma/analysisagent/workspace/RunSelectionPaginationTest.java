package com.kplasma.analysisagent.workspace;

import java.net.URI;
import java.net.http.*;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;
import tools.jackson.databind.JsonNode;
import static org.assertj.core.api.Assertions.*;

@TestPropertySource(properties="kplasma.agent.worker-token=synthetic-worker-token")
class RunSelectionPaginationTest extends WorkspaceTestSupport {
    String base;
    JsonNode pending;
    private JsonNode internal(String suffix,Object body)throws Exception{
        var req=HttpRequest.newBuilder(URI.create("http://localhost:"+port+"/internal/agent"+suffix)).header("Content-Type","application/json").header("X-Agent-Token","synthetic-worker-token").POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        var response=HttpClient.newHttpClient().send(req,HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);
    }
    private void open()throws Exception{open(Map.of());}
    private void open(Map<String,Object> reference)throws Exception{
        var job=ok("POST","/api/agent/requests",Map.of("text","비교해줘","stateToken",token()),UUID.randomUUID().toString());
        String id=job.get("requestId").stringValue();base="/api/agent/requests/"+id;
        var claim=internal("/claim",Map.of("workerId","test","leaseSeconds",60));
        var fence=new HashMap<String,Object>();fence.put("claimGeneration",claim.get("claimGeneration"));fence.put("requestRevision",claim.get("requestRevision"));fence.put("operationKind","compare_runs");
        internal("/requests/"+id+"/heartbeat",fence);
        if(!reference.isEmpty())jdbc.update("update agent_request set context_snapshot=jsonb_set(context_snapshot,'{comparisonReference}',?::jsonb) where id=?::uuid",mapper.writeValueAsString(reference),id);
        fence.put("pendingInput",Map.of("id","pick","type","run_selection","message","선택","minSelections",2,"baselineRequired",false));
        pending=internal("/requests/"+id+"/needs-input",fence);
    }
    private JsonNode page(String query)throws Exception{return ok("GET",base+"/run-options?format=2&pendingInputId=pick"+query,null,null);}
    private JsonNode selection()throws Exception{return ok("GET",base+"/run-selection?pendingInputId=pick",null,null);}
    private Map<String,Object> command(long revision,String operation){return new HashMap<>(Map.of("pendingInputId","pick","expectedRequestRevision",0,"expectedSelectionRevision",revision,"operation",operation));}
    private JsonNode mutate(Map<String,Object> body,String key)throws Exception{return ok("POST",base+"/run-selection",body,key);}

    @Test void boundedPagesKeepAliasesAndRejectMismatchedCursor()throws Exception{
        open();var first=page("&pageSize=2");assertThat(first.get("options").size()).isEqualTo(2);assertThat(first.get("totalCount").isNull()).isTrue();assertThat(ok("GET",base+"/run-options/count?pendingInputId=pick",null,null).get("totalCount").intValue()).isEqualTo(4);
        assertThat(first.get("format").intValue()).isEqualTo(2);
        var cursor=URLEncoder.encode(first.get("nextCursor").stringValue(),StandardCharsets.UTF_8);
        var next=page("&pageSize=2&cursor="+cursor);assertThat(next.get("options").get(0).get("key").stringValue()).isEqualTo("R3");assertThat(next.get("hasMore").booleanValue()).isFalse();
        assertThat(send("GET",base+"/run-options?format=2&pendingInputId=pick&query=other&cursor="+cursor,null,null).statusCode()).isEqualTo(400);
        assertThat(page("&query=%25").get("options").size()).isZero();
        assertThat(page("&query=SYNTHETIC-2").get("options").get(0).get("key").stringValue()).isEqualTo("R3");
        assertThat(page("&query=R1").get("options").get(0).get("key").stringValue()).isEqualTo("R1");
        var descending=page("&sort=descending&pageSize=2");assertThat(descending.get("options").get(0).get("key").stringValue()).isEqualTo("R4");
        var descendingNext=page("&sort=descending&pageSize=2&cursor="+URLEncoder.encode(descending.get("nextCursor").stringValue(),StandardCharsets.UTF_8));assertThat(descendingNext.get("options").get(0).get("key").stringValue()).isEqualTo("R2");assertThat(descendingNext.get("hasMore").booleanValue()).isFalse();
        assertThat(send("GET",base+"/run-options?pendingInputId=pick",null,null).statusCode()).isEqualTo(409);
        String context=jdbc.queryForObject("select context_snapshot::text from agent_request where id=?::uuid",String.class,pending.get("requestId").stringValue());
        assertThat(context).doesNotContain("conditions","unavailableReason");
    }

    @Test void selectionSurvivesSearchAndResumeOnlyTransfersChosenVersions()throws Exception{
        open();var add=command(0,"add");add.put("keys",List.of("R1","R3"));mutate(add,"add");
        page("&query=SYNTHETIC-1&sort=descending");var saved=selection();assertThat(saved.get("selectedCount").intValue()).isEqualTo(2);
        var baseline=command(1,"baseline");baseline.put("baselineKey","R3");mutate(baseline,"baseline");
        // Replaying an old add must not perform the mutation again or roll revision back.
        assertThat(mutate(add,"add").get("selectionRevision").intValue()).isEqualTo(2);
        assertThat(send("POST",base+"/run-selection",command(0,"clear"),"stale").statusCode()).isEqualTo(409);
        var selected=selection();var input=Map.of("type","run_selection","snapshotId",selected.get("snapshotId").stringValue(),"selectionRevision",2);
        var body=Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",input);
        assertThat(ok("POST",base+"/resume",body,"resume").get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(ok("POST",base+"/resume",body,"resume").get("status").stringValue()).isEqualTo("QUEUED");
        var row=mapper.readTree(jdbc.queryForObject("select context_snapshot::text from agent_request where id=?::uuid",String.class,pending.get("requestId").stringValue()));
        assertThat(row.get("comparisonReference").get("entries").size()).isEqualTo(2);assertThat(row.get("comparisonReference").get("baselineKey").stringValue()).isEqualTo("R3");
        assertThat(row.has("comparisonOptions")).isFalse();assertThat(jdbc.queryForObject("select count(*) from agent_run_selection",Integer.class)).isZero();
    }

    @Test void bulkScopesUnionAndDeletionDoesNotSubstituteVersions()throws Exception{
        open();var add=command(0,"add");add.put("keys",List.of("R1"));mutate(add,"page");
        var search=command(1,"search");search.put("query","SYNTHETIC-2");mutate(search,"search");assertThat(selection().get("selectedCount").intValue()).isEqualTo(2);
        mutate(command(2,"all"),"all");assertThat(selection().get("selectedCount").intValue()).isEqualTo(4);
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-3")),null);
        var selected=selection();assertThat(selected.get("selectedCount").intValue()).isEqualTo(4);assertThat(selected.get("unavailableCount").intValue()).isEqualTo(1);
        assertThat(page("&query=SYNTHETIC-3").get("options").size()).isZero();
        var body=Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","snapshotId",selected.get("snapshotId").stringValue(),"selectionRevision",3));
        assertThat(send("POST",base+"/resume",body,"bad").statusCode()).isEqualTo(400);
        mutate(command(3,"clear"),"clear");assertThat(selection().get("selectedCount").intValue()).isZero();
        ok("POST",base+"/cancel",Map.of(),"cancel");assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isZero();
    }

    @Test void latestCatalogueChangesWhileSelectedVersionsStayPinned()throws Exception{
        open();var before=page("").get("options");String old=before.get(0).get("ref").get("runVersionId").stringValue();var add=command(0,"add");add.put("keys",List.of("R1","R3"));mutate(add,"pin");var baseline=command(1,"baseline");baseline.put("baselineKey","R1");mutate(baseline,"baseline");UUID newer=UUID.randomUUID();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),summary||jsonb_build_object('runVersionId',?::text,'pressure',999),full_run from run_version where id=?::uuid",newer,newer.toString(),old);
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'",newer);
        jdbc.update("insert into run(run_id) values ('SYNTHETIC-10')");UUID added=UUID.randomUUID();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,'SYNTHETIC-10',source_id,now(),summary||jsonb_build_object('runId','SYNTHETIC-10','runVersionId',?::text),full_run from run_version where id=?::uuid",added,added.toString(),old);
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-10'",added);
        var latest=page("");assertThat(ok("GET",base+"/run-options/count?pendingInputId=pick",null,null).get("totalCount").intValue()).isEqualTo(5);
        assertThat(latest.get("options").get(0).get("ref").get("runVersionId").stringValue()).isEqualTo(newer.toString());
        assertThat(page("&query=999%20mTorr").get("options").size()).isEqualTo(1);
        var selected=selection();assertThat(selected.get("selectedCount").intValue()).isEqualTo(2);
        assertThat(selected.get("baselineKey").stringValue()).isEqualTo("R1");
        assertThat(selected.get("options").get(0).get("ref").get("runVersionId").stringValue()).isEqualTo(old);
        assertThat(selected.get("options").get(0).get("conditions")).isEqualTo(before.get(0).get("conditions"));
    }

    @Test void legacyInventoryIsNotCopiedAndOldAliasesCannotSelectOtherVersions()throws Exception{
        open();var original=page("").get("options");String id=pending.get("requestId").stringValue();
        jdbc.update("delete from agent_run_selection where request_id=?::uuid",id);
        jdbc.update("update agent_request set context_snapshot=jsonb_set(context_snapshot,'{comparisonOptions}',?::jsonb) where id=?::uuid",mapper.writeValueAsString(Map.of("pendingInputId","pick","options",original)),id);
        jdbc.update("update run_version set summary=jsonb_set(summary,'{pressure}','999')");
        assertThat(page("&query=999%20mTorr").get("options").size()).isEqualTo(4);
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isZero();
        var input=Map.of("expectedRequestRevision",0,"pendingInputId","pick","input",Map.of("type","run_selection","runKeys",List.of("R3","R1")));
        assertThat(send("POST",base+"/resume",input,"legacy").statusCode()).isEqualTo(400);
    }

    @Test void openingPagingAndSearchingDoNotCopyCandidates()throws Exception{
        open();assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isZero();
        page("&pageSize=2");page("&query=SYNTHETIC-2");selection();
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isZero();
        var add=command(0,"add");add.put("keys",List.of("R1","R3"));mutate(add,"two");
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isEqualTo(2);
        var remove=command(1,"remove");remove.put("keys",List.of("R1"));mutate(remove,"remove");
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isEqualTo(1);
        mutate(command(2,"clear"),"empty");assertThat(jdbc.queryForObject("select count(*) from agent_run_selection_option",Integer.class)).isZero();
    }

    @Test void selectionPinsTheDisplayedVersionEvenIfTheCatalogueUpdatesBeforeTheClick()throws Exception{
        open();String old=page("").get("options").get(0).get("ref").get("runVersionId").stringValue();UUID newer=UUID.randomUUID();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),summary,full_run from run_version where id=?::uuid",newer,old);
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'",newer);
        var add=command(0,"add");add.put("keys",List.of("R1"));mutate(add,"displayed-version");
        assertThat(selection().get("options").get(0).get("ref").get("runVersionId").stringValue()).isEqualTo(old);
        assertThat(page("").get("options").get(0).get("ref").get("runVersionId").stringValue()).isEqualTo(newer.toString());
    }

    @Test void concurrentSelectionWritesDoNotOverwriteEachOther()throws Exception{
        open();var left=command(0,"add");left.put("keys",List.of("R1"));var right=command(0,"add");right.put("keys",List.of("R2"));
        var client=HttpClient.newHttpClient();List<java.util.concurrent.CompletableFuture<HttpResponse<String>>> calls=new ArrayList<>();
        for(var body:List.of(left,right)){
            var req=HttpRequest.newBuilder(URI.create("http://localhost:"+port+base+"/run-selection")).header("Content-Type","application/json").header("Idempotency-Key",UUID.randomUUID().toString()).POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
            calls.add(client.sendAsync(req,HttpResponse.BodyHandlers.ofString()));
        }
        assertThat(calls.stream().map(c->c.join().statusCode()).toList()).containsExactlyInAnyOrder(200,409);
        assertThat(selection().get("selectedCount").intValue()).isEqualTo(1);
    }

    @Test void anAttachedHistoricalVersionKeepsItsAliasAlongsideTheCurrentVersion()throws Exception{
        UUID old=jdbc.queryForObject("select current_version_id from run where run_id='SYNTHETIC-0'",UUID.class);
        UUID current=UUID.randomUUID();
        jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) select ?,run_id,source_id,now(),summary,full_run from run_version where id=?",current,old);
        jdbc.update("update run set current_version_id=? where run_id='SYNTHETIC-0'",current);
        var ref=Map.of("runId","SYNTHETIC-0","runVersionId",old.toString());
        open(Map.of("entries",List.of(Map.of("key","R1","ref",ref))));
        var all=page("");assertThat(ok("GET",base+"/run-options/count?pendingInputId=pick",null,null).get("totalCount").intValue()).isEqualTo(5);
        Set<String> aliases=new HashSet<>();int historical=0;
        for(var option:all.get("options")){
            assertThat(aliases.add(option.get("key").stringValue())).isTrue();
            if(option.get("key").stringValue().equals("R1")){historical++;assertThat(option.get("ref").get("runVersionId").stringValue()).isEqualTo(old.toString());}
        }
        assertThat(historical).isEqualTo(1);
        Set<String> versions=new HashSet<>();String cursor="";
        do{
            var result=page("&pageSize=1&sort=descending"+cursor);
            assertThat(versions.add(result.get("options").get(0).get("ref").get("runVersionId").stringValue())).isTrue();
            cursor=result.get("hasMore").booleanValue()?"&cursor="+URLEncoder.encode(result.get("nextCursor").stringValue(),StandardCharsets.UTF_8):"";
        }while(!cursor.isEmpty());
        assertThat(versions).hasSize(5);
        String currentKey="";for(var option:all.get("options"))if(option.get("ref").get("runVersionId").stringValue().equals(current.toString()))currentKey=option.get("key").stringValue();
        var add=command(0,"add");add.put("keys",List.of("R1",currentKey));mutate(add,"historical");
        ok("POST","/api/runs/delete",Map.of("runIds",List.of("SYNTHETIC-0")),null);
        assertThat(selection().get("unavailableCount").intValue()).isEqualTo(2);
        assertThat(page("&query=SYNTHETIC-0").get("options").size()).isEqualTo(1);
        ok("POST","/api/workspace/new-conversation",Map.of("stateToken",token()),"new");
        assertThat(jdbc.queryForObject("select count(*) from agent_run_selection",Integer.class)).isZero();
        assertThat(send("GET",base+"/run-options?format=2&pendingInputId=pick",null,null).statusCode()).isEqualTo(409);
    }
}
