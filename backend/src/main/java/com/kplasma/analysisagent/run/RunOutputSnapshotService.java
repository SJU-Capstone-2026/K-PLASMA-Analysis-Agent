package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import com.kplasma.analysisagent.contract.RunOutputDto.Output;
import com.kplasma.analysisagent.ingestion.SourceStore;
import com.kplasma.analysisagent.ingestion.StoredBatch;
import com.kplasma.analysisagent.ingestion.StoredSource;
import com.kplasma.analysisagent.parser.ComparisonFeatureExtractor;
import com.kplasma.analysisagent.parser.KPlasmaGraphParser;
import com.kplasma.analysisagent.parser.ParseFailure;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class RunOutputSnapshotService implements ApplicationRunner {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ComparisonFeatureExtractor extractor;
    private final String backfillSourceRoot;

    public RunOutputSnapshotService(JdbcTemplate jdbc, ObjectMapper mapper, ComparisonFeatureExtractor extractor,
                                    @Value("${kplasma.outputs.backfill-source-root:${kplasma.iad.backfill-source-root:}}")
                                    String backfillSourceRoot) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.extractor = extractor;
        this.backfillSourceRoot = backfillSourceRoot;
    }

    public int save(Output output) {
        return jdbc.update("""
            insert into run_output_snapshot (run_version_id, output_id, compact_output, display)
            select id, ?, ?::jsonb, ?::jsonb from run_version where id=? for key share
            on conflict (run_version_id, output_id) do nothing
            """, output.metadata().outputId(), mapper.writeValueAsString(output.compact()),
            mapper.writeValueAsString(output.display()), UUID.fromString(output.metadata().ref().runVersionId()));
    }

    @Override
    public void run(ApplicationArguments args) throws IOException {
        if (backfillSourceRoot.isBlank()) return;
        var result = backfill(Path.of(backfillSourceRoot));
        LoggerFactory.getLogger(RunOutputSnapshotService.class).info(
            "Run output backfill: saved={} unavailable={}", result.saved(), result.unavailable());
    }

    public record BackfillResult(int saved, int unavailable) {}

    private record Original(long sequence, RunRef ref, UUID sourceId, String sourceHash,
                            String storagePath, long size, String fileHash) {}

    public BackfillResult backfill(Path sourceRoot) throws IOException {
        var root = sourceRoot.toRealPath();
        int saved = 0;
        int unavailable = 0;
        for (var id : ComparisonFeatureExtractor.IDS.stream().sorted().toList()) {
            var result = backfillOutput(root, id);
            saved += result.saved();
            unavailable += result.unavailable();
            LoggerFactory.getLogger(RunOutputSnapshotService.class).info(
                "Run output backfill [{}]: saved={} unavailable={}", id, result.saved(), result.unavailable());
        }
        return new BackfillResult(saved, unavailable);
    }

    private BackfillResult backfillOutput(Path root, String outputId) {
        var relative = KPlasmaGraphParser.path(outputId);
        long cursor = 0;
        int saved = 0;
        int unavailable = 0;
        while (true) {
            var batch = jdbc.query("""
                select v.registration_sequence, v.run_id, v.id, s.id source_id, s.sha256 source_hash,
                       f.storage_path, f.size, f.sha256 file_hash
                from run_version v join source_set s on s.id=v.source_id
                left join source_file f on f.source_id=s.id and f.relative_path=?
                where v.registration_sequence>? and (? or (v.summary->>'biasPower')::double precision>0)
                  and not exists (select 1 from run_output_snapshot o where o.run_version_id=v.id and o.output_id=?)
                order by v.registration_sequence limit 100
                """, (rs, index) -> new Original(rs.getLong("registration_sequence"),
                new RunRef(rs.getString("run_id"), rs.getString("id")), rs.getObject("source_id", UUID.class),
                rs.getString("source_hash"), rs.getString("storage_path"), rs.getLong("size"), rs.getString("file_hash")),
                relative, cursor, outputId.equals("residual"), outputId);
            if (batch.isEmpty()) return new BackfillResult(saved, unavailable);
            for (var original : batch) {
                try {
                    if (original.storagePath() == null) {
                        unavailable++;
                        continue;
                    }
                    var path = root.resolve(original.storagePath()).normalize();
                    if (!path.startsWith(root) || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)
                        || !path.toRealPath().startsWith(root)) {
                        unavailable++;
                        continue;
                    }
                    var file = new StoredBatch.File(relative, path, original.size(), original.fileHash(), outputId);
                    if (!SourceStore.matchesHash(file)) {
                        unavailable++;
                        continue;
                    }
                    var source = new StoredSource(original.sourceId(), "", Map.of(relative, file), original.sourceHash());
                    var output = extractor.extract(source, original.ref(), outputId, true);
                    saved += save(output);
                } catch (IOException | ParseFailure ex) {
                    unavailable++;
                }
            }
            cursor = batch.getLast().sequence();
        }
    }
}
