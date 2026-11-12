package com.kplasma.analysisagent.agent.v3;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import java.util.*;
import java.util.regex.Pattern;

/** Treat Run names as opaque identities; never derive scientific conditions from their spelling. */
public final class V3NamedRunResolver {
    private V3NamedRunResolver() {}
    // ASCII boundaries allow Korean particles ("RUN-ART-A의") but reject longer IDs and prefixed IDs.
    private static final Pattern NAME = Pattern.compile("(?<![A-Za-z0-9_-])RUN-[A-Za-z0-9][A-Za-z0-9_-]*(?![A-Za-z0-9_-])", Pattern.CASE_INSENSITIVE);

    public static List<String> mentions(String question) {
        var result = new LinkedHashMap<String,String>();
        var matches = NAME.matcher(question);
        while (matches.find()) result.putIfAbsent(matches.group().toLowerCase(Locale.ROOT), matches.group());
        return List.copyOf(result.values());
    }

    public record Resolution(List<RunRef> references,List<Map<String,Object>> bindings,
                             List<String> unresolved,List<Map<String,Object>> issues) {
        public void putInto(Map<String,Object> context) {
            context.put("namedRunReferences",references);
            context.put("namedRunBindings",bindings);
            context.put("unresolvedRunNames",unresolved);
            context.put("namedRunResolutionIssues",issues);
        }
    }

    public static Resolution resolve(List<String> mentions,List<RunRef> catalog,List<RunRef> attached) {
        List<RunRef> refs = new ArrayList<>();
        List<Map<String,Object>> bindings = new ArrayList<>();
        List<String> unresolved = new ArrayList<>();
        List<Map<String,Object>> issues = new ArrayList<>();
        for (String mention : mentions) {
            // An explicit historical attachment takes precedence over today's catalog version.
            var explicit = attached.stream().filter(ref -> ref.runId().equalsIgnoreCase(mention)).distinct().toList();
            var matches = explicit.isEmpty()
                ? catalog.stream().filter(ref -> ref.runId().equalsIgnoreCase(mention)).distinct().toList() : explicit;
            if (matches.size() != 1) {
                unresolved.add(mention);
                String reason = matches.isEmpty() ? "NOT_FOUND"
                    : matches.stream().map(RunRef::runId).distinct().count() > 1 ? "AMBIGUOUS_NAME" : "AMBIGUOUS_VERSION";
                issues.add(Map.of("name",mention,"reason",reason));
                continue;
            }
            RunRef ref = matches.getFirst();
            refs.add(ref);
            bindings.add(Map.of("name",ref.runId(),"ref",ref,
                "source",Map.of("message_key","question","quote",mention)));
        }
        return new Resolution(List.copyOf(refs),List.copyOf(bindings),List.copyOf(unresolved),List.copyOf(issues));
    }
}
