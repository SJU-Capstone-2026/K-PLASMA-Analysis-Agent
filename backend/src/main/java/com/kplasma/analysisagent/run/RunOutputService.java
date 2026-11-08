package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunOutputDto.*;
import com.kplasma.analysisagent.ingestion.IntakeException;
import com.kplasma.analysisagent.parser.ComparisonFeatureExtractor;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunOutputService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ComparisonFeatureExtractor extractor;

    public RunOutputService(JdbcTemplate jdbc, ObjectMapper mapper, ComparisonFeatureExtractor extractor) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.extractor = extractor;
    }

    private static void require(boolean valid) {
        if (!valid) throw new IntakeException("INVALID_OUTPUT_QUERY", 400,
            "Exact Run references and supported output IDs are required (maximum 50 Runs)");
    }

    private record Version(String runId, boolean biasOn, String sourceHash, Map<String, Output> outputs) {}

    public Response outputs(Request body, boolean display) {
        require(body != null && body.runRefs() != null && body.plotIds() != null);
        var refs = body.runRefs();
        var ids = body.plotIds();
        require(!refs.isEmpty() && refs.size() <= 50 && new HashSet<>(refs).size() == refs.size()
            && !ids.isEmpty() && ids.size() <= 7 && new HashSet<>(ids).size() == ids.size()
            && ids.stream().allMatch(id -> id != null && ComparisonFeatureExtractor.IDS.contains(id)));

        var args = new ArrayList<Object>();
        args.addAll(ids);
        for (var ref : refs) {
            require(ref != null && ref.runId() != null && ref.runVersionId() != null);
            try {
                args.add(UUID.fromString(ref.runVersionId()));
            } catch (IllegalArgumentException ex) {
                require(false);
            }
        }

        Map<String, Version> versions = new HashMap<>();
        var sql = """
            select v.id, v.run_id, (v.summary->>'biasPower')::double precision>0 as bias_on,
                   s.sha256, o.output_id, o.compact_output, %s as display
            from run_version v join source_set s on s.id=v.source_id
            left join run_output_snapshot o on o.run_version_id=v.id and o.output_id in (%s)
            where v.id in (%s)
            """.formatted(display ? "o.display" : "null", String.join(",", Collections.nCopies(ids.size(), "?")),
                String.join(",", Collections.nCopies(refs.size(), "?")));
        jdbc.query(sql, rs -> {
            String versionId = rs.getString("id");
            var version = versions.get(versionId);
            if (version == null) {
                version = new Version(rs.getString("run_id"), rs.getBoolean("bias_on"), rs.getString("sha256"),
                    new HashMap<>());
                versions.put(versionId, version);
            }
            String id = rs.getString("output_id");
            if (id == null) return;
            var compact = mapper.readValue(rs.getString("compact_output"), Output.class);
            var output = display
                ? new Output(compact.metadata(), compact.features(), mapper.readValue(rs.getString("display"), Display.class))
                : compact;
            version.outputs().put(id, output);
        }, args.toArray());

        List<Output> result = new ArrayList<>();
        for (var ref : refs) {
            var version = versions.get(ref.runVersionId());
            for (var id : ids) {
                if (version == null || !version.runId().equals(ref.runId())) {
                    result.add(extractor.unavailable(ref, id, "VERSION_UNAVAILABLE", null));
                    continue;
                }
                var output = version.outputs().get(id);
                if (output == null) {
                    String reason = !version.biasOn() && !id.equals("residual") ? "BIAS_OFF"
                        : id.equals("iad") ? "IAD_NOT_INDEXED" : "OUTPUT_NOT_INDEXED";
                    output = extractor.unavailable(ref, id, reason, version.sourceHash());
                }
                result.add(output);
            }
        }
        return new Response(List.copyOf(result));
    }
}
