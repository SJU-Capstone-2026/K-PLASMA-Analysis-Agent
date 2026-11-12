package com.kplasma.analysisagent.agent.v3;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;

/** Request-owned switches. Numeric validation and Decisions are never switched off. */
public final class V3Options {
    private V3Options() {}
    public static Map<String,Object> freeze(String version, Map<String,Object> supplied) {
        if (!"v3".equals(version)) {
            require(supplied == null, "v3Options may only be supplied to graph v3");
            return null;
        }
        require(supplied != null && supplied.keySet().equals(Set.of("rulesEnabled", "ragEnabled")),
            "Graph v3 requires explicit rulesEnabled and ragEnabled booleans");
        require(supplied.get("rulesEnabled") instanceof Boolean && supplied.get("ragEnabled") instanceof Boolean,
            "V3 switches must be booleans");
        boolean rules=(Boolean)supplied.get("rulesEnabled"), rag=(Boolean)supplied.get("ragEnabled");
        // Python json.dumps(sort_keys=True,separators=(',',':')) uses this exact byte order.
        String canonical="{\"ragEnabled\":"+rag+",\"rulesEnabled\":"+rules+"}";
        return Map.of("rulesEnabled", rules, "ragEnabled", rag, "configDigest", sha(canonical));
    }
    public static boolean validSnapshot(JsonNode value) {
        if(value == null || !value.isObject() || value.size()!=3
            || !value.path("rulesEnabled").isBoolean() || !value.path("ragEnabled").isBoolean()
            || !value.path("configDigest").isString()) return false;
        var expected=freeze("v3",Map.of("rulesEnabled",value.path("rulesEnabled").asBoolean(),
            "ragEnabled",value.path("ragEnabled").asBoolean()));
        return expected.get("configDigest").equals(value.path("configDigest").asString());
    }
    public static void allowAction(Map<String,Object> options,String action) {
        require(options!=null,"Missing frozen V3 switches");
        require("search".equals(action) || "cost_exclusion".equals(action),"Unknown V3 decision action");
        require(Boolean.TRUE.equals(options.get("search".equals(action)?"ragEnabled":"rulesEnabled")),
            "Requested V3 decision feature is disabled");
    }
    public static void require(boolean valid,String message) {
        if(!valid)throw new IntakeException("INVALID_V3_OPTIONS",400,message);
    }
    private static String sha(String value) {
        try {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
        catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
    }
}
