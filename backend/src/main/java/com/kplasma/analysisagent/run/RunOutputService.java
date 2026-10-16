package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto;
import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.RunOutputDto.*;
import com.kplasma.analysisagent.ingestion.*;
import com.kplasma.analysisagent.parser.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunOutputService {
    private static final org.slf4j.Logger LOG=org.slf4j.LoggerFactory.getLogger(RunOutputService.class);
    private final JdbcTemplate jdbc;private final ObjectMapper mapper;private final SourceStore store;private final ComparisonFeatureExtractor extractor;
    private final Map<String,Output> cache=new LinkedHashMap<>(64,.75f,true);
    public RunOutputService(JdbcTemplate jdbc,ObjectMapper mapper,SourceStore store,ComparisonFeatureExtractor extractor){this.jdbc=jdbc;this.mapper=mapper;this.store=store;this.extractor=extractor;}
    private static void require(boolean valid){if(!valid)throw new IntakeException("INVALID_OUTPUT_QUERY",400,"Exact Run references and supported output IDs are required (maximum 50 Runs)");}
    public Response outputs(Request body,boolean display){
        require(body!=null&&body.runRefs()!=null&&body.plotIds()!=null);
        long started=System.nanoTime();int cacheHits=0,extractions=0;var refs=body.runRefs();var ids=body.plotIds();require(!refs.isEmpty()&&refs.size()<=50&&new HashSet<>(refs).size()==refs.size()&&!ids.isEmpty()&&ids.size()<=7&&new HashSet<>(ids).size()==ids.size()&&ComparisonFeatureExtractor.IDS.containsAll(ids));
        List<UUID> versions=new ArrayList<>();for(var ref:refs){require(ref!=null&&ref.runId()!=null&&ref.runVersionId()!=null);try{versions.add(UUID.fromString(ref.runVersionId()));}catch(IllegalArgumentException ex){require(false);}}
        record Source(RunDto.Summary summary,UUID id,String hash,Map<String,StoredBatch.File> files) {}
        Map<String,Source> sources=new HashMap<>();
        // One bounded SQL statement for all requested versions and retained file manifests; no full_run hydration.
        jdbc.query("select v.id,v.summary,s.id source_id,s.sha256,f.relative_path,f.storage_path,f.size,f.sha256 file_hash,f.kind from run_version v join source_set s on s.id=v.source_id left join source_file f on f.source_id=s.id where v.id in ("+String.join(",",Collections.nCopies(versions.size(),"?"))+")",rs->{
            String version=rs.getString("id");var source=sources.get(version);if(source==null){source=new Source(mapper.readValue(rs.getString("summary"),RunDto.Summary.class),rs.getObject("source_id",UUID.class),rs.getString("sha256"),new HashMap<>());sources.put(version,source);}
            String relative=rs.getString("relative_path");if(relative!=null){Path path=store.root().resolve(rs.getString("storage_path")).toAbsolutePath().normalize();require(path.startsWith(store.root().toAbsolutePath().normalize()));source.files().put(relative,new StoredBatch.File(relative,path,rs.getLong("size"),rs.getString("file_hash"),rs.getString("kind")));}
        },versions.toArray());
        List<Output> result=new ArrayList<>();
        for(var ref:refs)for(String id:ids){
            var source=sources.get(ref.runVersionId());Output output;
            if(source==null||!source.summary().runId().equals(ref.runId()))output=extractor.unavailable(ref,id,"VERSION_UNAVAILABLE",null);
            else {
                var stored=new StoredSource(source.id(),"",source.files(),source.hash());String key=ref.runVersionId()+":"+id+":"+source.hash()+":"+ComparisonFeatureExtractor.POLICY;
                // Synchronization also coalesces identical concurrent source reads; the cache is bounded.
                synchronized(cache){
                    output=cache.get(key);if(output!=null)cacheHits++;
                    var file=source.files().get(KPlasmaGraphParser.path(id));
                    if(file!=null&&!Files.isRegularFile(file.path(),LinkOption.NOFOLLOW_LINKS)){cache.remove(key);output=extractor.unavailable(ref,id,"SOURCE_MISSING",source.hash());}
                    else if(output==null){
                        extractions++;
                        try {
                            if(file!=null&&!hashMatches(file))output=extractor.unavailable(ref,id,"SOURCE_INTEGRITY_MISMATCH",source.hash());
                            else output=extractor.extract(stored,ref,id,source.summary().biasPower()>0);
                        }catch(ParseFailure|java.io.IOException ex){output=extractor.unavailable(ref,id,"SOURCE_INVALID",source.hash());}
                        if(output.metadata().status().equals("AVAILABLE")||"BIAS_OFF".equals(output.metadata().reason()))cache.put(key,output);if(cache.size()>512)cache.remove(cache.keySet().iterator().next());
                    }
                }
            }
            result.add(display?output:output.compact());
        }
        LOG.debug("comparison outputs: runs={} outputs={} manifestQueries=1 cacheHits={} extractions={} durationMs={}",refs.size(),result.size(),cacheHits,extractions,(System.nanoTime()-started)/1_000_000.0);
        return new Response(List.copyOf(result));
    }
    private boolean hashMatches(StoredBatch.File file)throws java.io.IOException{
        try(var input=Files.newInputStream(file.path())){var digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[8192];int n;while((n=input.read(buffer))!=-1)digest.update(buffer,0,n);return HexFormat.of().formatHex(digest.digest()).equals(file.sha256());}
        catch(NoSuchAlgorithmException ex){throw new IllegalStateException(ex);}
    }
}
