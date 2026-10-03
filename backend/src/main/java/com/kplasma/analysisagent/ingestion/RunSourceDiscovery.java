package com.kplasma.analysisagent.ingestion;

import java.util.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** Structural discovery only. INI conditions and completeness belong to the parser/worker. */
@Component
public class RunSourceDiscovery {
    private static final Pattern GRID_ROOT = Pattern.compile("(?:^|/)(PRS_\\d+/Source_\\d+/Bias_\\d+)(?:/|$)");
    public List<StoredSource> discover(StoredBatch batch) {
        Set<String> roots = new TreeSet<>();
        for (var file : batch.files()) {
            String path = file.relativePath();
            if (SourceStore.operatingSystemMetadata(path)) continue;
            if (path.equals("0d_setting.ini") || path.endsWith("/0d_setting.ini")) roots.add(path.substring(0, path.length() - "0d_setting.ini".length()));
            int result = path.indexOf("0d_result/");
            if (result == 0 || result > 0 && path.charAt(result - 1) == '/') roots.add(path.substring(0, result));
            var match = GRID_ROOT.matcher(path);
            if (match.find()) roots.add(path.substring(0, match.end(1)) + "/");
        }
        // Overlapping Run roots would assign originals ambiguously; never merge unrelated Runs.
        for (String root : roots) for (String other : roots) if (!root.equals(other) && other.startsWith(root))
            throw IntakeException.invalid("Overlapping Run roots");
        List<StoredSource> sources = new ArrayList<>();
        for (String root : roots) {
            Map<String, StoredBatch.File> files = new TreeMap<>();
            for (var file : batch.files()) if (file.relativePath().startsWith(root) && !SourceStore.operatingSystemMetadata(file.relativePath()))
                files.put(file.relativePath().substring(root.length()), file);
            if (!files.isEmpty()) sources.add(new StoredSource(UUID.randomUUID(), root, files, SourceStore.hashFiles(files)));
        }
        if (sources.isEmpty()) throw IntakeException.invalid("No Run source directories found");
        return List.copyOf(sources);
    }
}
