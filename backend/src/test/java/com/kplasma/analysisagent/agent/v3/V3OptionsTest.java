package com.kplasma.analysisagent.agent.v3;

import com.kplasma.analysisagent.ingestion.IntakeException;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import static org.junit.jupiter.api.Assertions.*;

class V3OptionsTest {
    private final ObjectMapper mapper=new ObjectMapper();
    @Test void allFourModesAreExplicitAndHashOrderIndependent() {
        for(boolean rules:new boolean[]{false,true})for(boolean rag:new boolean[]{false,true}) {
            var first=V3Options.freeze("v3",Map.of("rulesEnabled",rules,"ragEnabled",rag));
            var reversed=new LinkedHashMap<String,Object>();reversed.put("ragEnabled",rag);reversed.put("rulesEnabled",rules);
            assertEquals(first,V3Options.freeze("v3",reversed));
            assertTrue(V3Options.validSnapshot(mapper.valueToTree(first)));
            assertThrows(UnsupportedOperationException.class,()->first.put("ragEnabled",!rag));
        }
    }
    @Test void missingStringOrUnknownSwitchesAreRejected() {
        assertThrows(IntakeException.class,()->V3Options.freeze("v3",null));
        assertThrows(IntakeException.class,()->V3Options.freeze("v3",Map.of("ragEnabled",true)));
        assertThrows(IntakeException.class,()->V3Options.freeze("v3",Map.of("rulesEnabled","true","ragEnabled",true)));
        assertThrows(IntakeException.class,()->V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",true,"configDigest","forged")));
        assertThrows(IntakeException.class,()->V3Options.freeze("v1",Map.of("rulesEnabled",true,"ragEnabled",true)));
        assertThrows(IntakeException.class,()->V3Options.freeze("v2",Map.of("rulesEnabled",true,"ragEnabled",true)));
        assertNull(V3Options.freeze("v1",null));assertNull(V3Options.freeze("v2",null));
    }
    @Test void actionCannotBypassDisabledMode() {
        var rulesOnly=V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",false));
        V3Options.allowAction(rulesOnly,"cost_exclusion");
        assertThrows(IntakeException.class,()->V3Options.allowAction(rulesOnly,"search"));
        var ragOnly=V3Options.freeze("v3",Map.of("rulesEnabled",false,"ragEnabled",true));
        V3Options.allowAction(ragOnly,"search");
        assertThrows(IntakeException.class,()->V3Options.allowAction(ragOnly,"cost_exclusion"));
        assertThrows(IntakeException.class,()->V3Options.allowAction(rulesOnly,"unknown"));
    }
    @Test void digestChangesWhenEitherFeatureChangesAndForgedDigestIsRejected() {
        var both=V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",true));
        assertEquals("a6d170b755e57478463b8b6634f1e649bc493b554b9bef4e63772543f439d882",
            V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",false)).get("configDigest"));
        assertNotEquals(both.get("configDigest"),V3Options.freeze("v3",Map.of("rulesEnabled",true,"ragEnabled",false)).get("configDigest"));
        assertNotEquals(both.get("configDigest"),V3Options.freeze("v3",Map.of("rulesEnabled",false,"ragEnabled",true)).get("configDigest"));
        var tampered=new LinkedHashMap<>(both);tampered.put("ragEnabled",false);
        assertFalse(V3Options.validSnapshot(mapper.valueToTree(tampered)));
    }
}
