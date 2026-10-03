package com.kplasma.analysisagent.workspace;

import java.net.*;
import java.net.http.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.*;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.*;
import tools.jackson.databind.node.*;
import static org.assertj.core.api.Assertions.*;

@Testcontainers
@DirtiesContext(classMode=DirtiesContext.ClassMode.AFTER_CLASS)
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties="kplasma.worker.enabled=false")
public abstract class WorkspaceTestSupport {
    @Container static final PostgreSQLContainer DB=new PostgreSQLContainer("postgres:18.6-alpine3.24");
    static final Path ROOT=temp();
    @DynamicPropertySource static void properties(DynamicPropertyRegistry r) {r.add("spring.datasource.url",DB::getJdbcUrl);r.add("spring.datasource.username",DB::getUsername);r.add("spring.datasource.password",DB::getPassword);r.add("kplasma.storage-root",ROOT::toString);}
    @Autowired protected ObjectMapper mapper; @Autowired protected JdbcTemplate jdbc; @LocalServerPort int port;
    protected List<JsonNode> refs;
    @BeforeEach void seed() throws Exception {
        var state=send("GET","/api/workspace",null,null);assertThat(state.statusCode()).isEqualTo(200);
        ok("POST","/api/workspace/reset",Map.of("stateToken",json(state).get("stateToken")),null);
        jdbc.execute("truncate import_batch, source_set, run cascade");
        refs=new ArrayList<>();
        var template=mapper.readTree(Files.readString(Path.of("../agent/tests/support/contract-wire.json"))).get("on");
        for(int i=0;i<4;i++) {
            String runId="SYNTHETIC-"+i;UUID version=UUID.randomUUID(),source=UUID.randomUUID();
            ObjectNode full=(ObjectNode)template.deepCopy();full.put("runId",runId);full.put("runVersionId",version.toString());
            jdbc.update("insert into source_set(id,sha256,total_bytes) values (?,?,1)",source,String.format("%064d",i));
            jdbc.update("insert into source_file(source_id,relative_path,kind,size,sha256,storage_path) values (?,'original.txt','OTHER',1,?,?)",source,String.format("%064d",i),ROOT.resolve("original.txt").toString());
            Files.writeString(ROOT.resolve("original.txt"),"artificial original");
            jdbc.update("insert into run(run_id) values (?)",runId);
            jdbc.update("insert into run_version(id,run_id,source_id,registered_at,summary,full_run) values (?,?,?,now(),?::jsonb,?::jsonb)",version,runId,source,full.toString(),full.toString());
            jdbc.update("update run set current_version_id=? where run_id=?",version,runId);
            refs.add(mapper.valueToTree(Map.of("runId",runId,"runVersionId",version.toString())));
        }
    }
    protected HttpResponse<String> send(String method,String path,Object body,String key) throws Exception {
        var request=HttpRequest.newBuilder(URI.create("http://localhost:"+port+path)).header("Content-Type","application/json");
        if(key!=null)request.header("Idempotency-Key",key);
        return HttpClient.newHttpClient().send(request.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
    }
    protected JsonNode json(HttpResponse<String> response) {return mapper.readTree(response.body());}
    protected JsonNode ok(String method,String path,Object body,String key) throws Exception {var response=send(method,path,body,key);assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(200);return json(response);}
    protected JsonNode state() throws Exception {return ok("GET","/api/workspace",null,null);}
    protected JsonNode token() throws Exception {return state().get("stateToken");}
    protected ObjectNode turn() {
        return (ObjectNode)mapper.valueToTree(Map.of("id",UUID.randomUUID().toString(),"askedAt","2026-01-01T00:00:00Z","question","artificial <script>note</script>","intent","REVERSE_SEARCH","context",refs.get(0),"answerRunRefs",refs.subList(0,2),"answerSnapshot",Map.of("summary","frozen answer","candidateRunRefs",List.of(refs.get(1)),"memoryRequest",Map.of("referenceRunRefs",List.of(refs.get(0))),"runSummary",Map.of("runId","SYNTHETIC-1","metrics",Map.of("ionFlux",1),"qualityStatus","VERIFIED")),"ui",Map.of("collapsed",false,"openRunIds",List.of(),"runDetailTabs",Map.of(),"activeCandidateGroup","common","lookupExpanded",false)));
    }
    protected ObjectNode review() {
        return (ObjectNode)mapper.valueToTree(Map.ofEntries(Map.entry("reviewId","REV-artificial"),Map.entry("targetRunId","SYNTHETIC-0"),Map.entry("comparedRunIds",List.of()),Map.entry("targetRunRef",refs.get(0)),Map.entry("comparedRunRefs",List.of()),Map.entry("decision","HOLD"),Map.entry("comment","<script>stored as text</script>"),Map.entry("authorName","tester"),Map.entry("createdAt","2026-01-01T00:00:00Z"),Map.entry("analysisType","FORWARD"),Map.entry("processMode","CONDITION_LOOKUP"),Map.entry("constraints",List.of()),Map.entry("goals",List.of()),Map.entry("queryText","artificial question"),Map.entry("evidenceKinds",List.of()),Map.entry("limitations",List.of()),Map.entry("runSnapshots",List.of(snapshot(0,false)))));
    }
    protected ObjectNode experiment() {
        ObjectNode record=review();record.remove(List.of("constraints","evidenceKinds","limitations","runSnapshots"));
        record.put("reviewId","EXP-artificial");record.put("id","EXP-artificial");record.put("version",2);record.put("analysisType","REVERSE");record.put("processMode","GOAL_RECOMMENDATION");record.put("decision","ADOPT");record.put("question","artificial question");record.put("overallComment","common comment");record.put("comment","common comment");record.set("objectives",mapper.valueToTree(List.of()));record.set("candidates",mapper.valueToTree(List.of(snapshot(0,true))));return record;
    }
    protected ObjectNode snapshot(int index,boolean candidate) {
        ObjectNode s=(ObjectNode)refs.get(index).deepCopy();s.set("conditions",mapper.valueToTree(Map.of("pressure",2,"sourcePower",100,"biasPower",200)));s.set("metrics",mapper.valueToTree(Map.of("ionFlux",1,"meanIonEnergy",2,"iedWidth",3)));
        if(candidate) {s.put("decision",index==0?"ADOPT":"HOLD");s.put("note","");s.set("objectiveEvaluations",mapper.valueToTree(List.of()));}
        else s.set("supportingMetrics",mapper.valueToTree(Map.of("electronDensity",19,"electronTemperature",2)));return s;
    }
    protected Map<String,Object> write(JsonNode record) throws Exception {List<JsonNode> selected=new ArrayList<>();selected.add(record.get("targetRunRef"));record.get("comparedRunRefs").forEach(selected::add);return Map.of("workspaceEpoch",token().get("workspaceEpoch").longValue(),"record",record,"runRefs",selected);}
    protected void rejects(String method,String path,Object body,String key,int status,String code) throws Exception {var response=send(method,path,body,key);assertThat(response.statusCode()).describedAs(response.body()).isEqualTo(status);assertThat(json(response).get("code").stringValue()).isEqualTo(code);assertThat(json(response).get("requestId").stringValue()).isNotBlank();}
    static Path temp() {try{return Files.createTempDirectory("workspace-test-");}catch(Exception e){throw new ExceptionInInitializerError(e);}}
}
