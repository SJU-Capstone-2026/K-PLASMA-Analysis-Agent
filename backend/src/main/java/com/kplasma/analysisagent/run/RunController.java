package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.ImportDto.*;
import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.contract.RunDeletionDto;
import com.kplasma.analysisagent.ingestion.*;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController @RequestMapping("/api")
public class RunController {
    private final RunQueryService query;
    private final RunRepository repository;
    private final ImportWorker imports;
    private final RunDeletionService deletion;
    public RunController(RunQueryService query,RunRepository repository,ImportWorker imports,RunDeletionService deletion) {this.query=query;this.repository=repository;this.imports=imports;this.deletion=deletion;}
    @GetMapping("/runs") public List<RunDto.Summary> runs() {return query.listSearchable();}
    @PostMapping("/runs/delete") public RunDeletionDto.Result delete(@RequestBody RunDeletionDto.Request request) {return deletion.delete(request);}
    @GetMapping("/run-versions/{id}") public RunDto.Full version(@PathVariable String id) {return query.getVersion(uuid(id));}
    @GetMapping("/catalog")
    public CatalogView catalog(@RequestParam(defaultValue="") String search,@RequestParam(defaultValue="") String status,@RequestParam(defaultValue="") String quality) {
        String term=search.strip().toLowerCase(Locale.ROOT);
        Map<String,List<RunDto.SourceFile>> files=new LinkedHashMap<>();
        var runs=repository.catalogRuns().stream().filter(row->{
            var run=row.summary();
            if(!status.isEmpty()&&!run.catalogStatus().equals(status)||!quality.isEmpty()&&!run.qualityStatus().equals(quality))return false;
            var sourceFiles=row.sourceFiles();
            boolean matches=term.isEmpty()||run.runId().toLowerCase(Locale.ROOT).contains(term)||sourceFiles.stream().anyMatch(f->f.name().toLowerCase(Locale.ROOT).contains(term));
            if(matches)files.put(run.runVersionId(),sourceFiles);
            return matches;
        }).map(RunRepository.CatalogRun::summary).toList();
        var jobs=imports.jobs().stream().filter(j->(status.isEmpty()||j.status().equals(status))&&(term.isEmpty()||(j.runId()!=null&&j.runId().toLowerCase(Locale.ROOT).contains(term)))).toList();
        return new CatalogView(runs,jobs,files);
    }
    @GetMapping("/import-jobs/{id}/files") public List<ManifestFile> files(@PathVariable String id) {return imports.files(uuid(id));}
    @PostMapping("/import-jobs/{id}/reprocess")
    public ResponseEntity<BatchView> reprocess(@PathVariable String id,@RequestHeader(name="Idempotency-Key",required=false) String key) {return ResponseEntity.accepted().body(imports.reprocess(uuid(id),key));}
    private UUID uuid(String id) {try{return UUID.fromString(id);}catch(IllegalArgumentException e){throw new IntakeException("INVALID_IDENTIFIER",400,"Invalid identifier");}}
}
