package com.kplasma.analysisagent.agent.v3;

import com.kplasma.analysisagent.contract.RunDto.RunRef;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class V3NamedRunResolverTest {
    private static final RunRef A=new RunRef("RUN-ART-A","00000000-0000-4000-8000-000000000001");
    private static final RunRef B=new RunRef("RUN-ART-B","00000000-0000-4000-8000-000000000002");
    private static final RunRef OLD_A=new RunRef(A.runId(),"00000000-0000-4000-8000-000000000003");
    private V3NamedRunResolver.Resolution resolve(String question,List<RunRef> attached) {
        return V3NamedRunResolver.resolve(V3NamedRunResolver.mentions(question),List.of(A,B),attached);
    }
    @Test void plainNamedRunResolvesWithoutAnyAttachment() {
        var result=resolve("RUN-ART-A 의 과거 판단기록좀 보여줘",List.of());
        assertThat(result.references()).containsExactly(A);
        assertThat(result.unresolved()).isEmpty();
        assertThat(result.bindings().getFirst()).containsEntry("name",A.runId()).containsEntry("ref",A)
            .containsEntry("source",Map.of("message_key","question","quote",A.runId()));
    }
    @Test void lowercaseKoreanParticleAndPunctuationKeepTheExactQuote() {
        var result=resolve("(run-art-a)의 기록을 보여줘.",List.of());
        assertThat(result.references()).containsExactly(A);
        assertThat(result.bindings().getFirst()).containsEntry("source",Map.of("message_key","question","quote","run-art-a"));
        assertThat(resolve("RUN-ART-A의 기록",List.of()).references()).containsExactly(A);
    }
    @Test void multipleNamesAreOrderedAndRepeatedNamesAreNotNewSources() {
        var result=resolve("RUN-ART-B, RUN-ART-A 및 run-art-b를 비교해줘",List.of());
        assertThat(result.references()).containsExactly(B,A);
    }
    @Test void partialLongerOrPrefixedIdentifiersCannotSelectAShorterRegisteredName() {
        var result=resolve("X-RUN-ART-A RUN-ART-A-EXTRA의 기록",List.of());
        assertThat(result.references()).isEmpty();
        assertThat(result.unresolved()).containsExactly("RUN-ART-A-EXTRA");
        assertThat(result.issues()).containsExactly(Map.of("name","RUN-ART-A-EXTRA","reason","NOT_FOUND"));
    }
    @Test void unknownAndKnownNamesRemainExplicitSoTheCallerCannotSilentlyAnswerOnlyTheKnownOne() {
        var result=resolve("RUN-ART-A와 RUN-ART-MISSING 기록",List.of());
        assertThat(result.references()).containsExactly(A);
        assertThat(result.unresolved()).containsExactly("RUN-ART-MISSING");
    }
    @Test void aNameWithNumericLookingPartsDoesNotGenerateAnExperiment() {
        var result=resolve("RUN-P99-S999-B9999 기록",List.of());
        assertThat(result.references()).isEmpty();
        assertThat(result.unresolved()).containsExactly("RUN-P99-S999-B9999");
    }
    @Test void explicitlyAttachedHistoricalVersionIsNotReplacedWithTheCurrentCatalogVersion() {
        var result=resolve("RUN-ART-A 기록",List.of(OLD_A));
        assertThat(result.references()).containsExactly(OLD_A);
    }
    @Test void severalExplicitVersionsOfTheSameNameRequireClarification() {
        var result=resolve("RUN-ART-A 기록",List.of(A,OLD_A));
        assertThat(result.references()).isEmpty();
        assertThat(result.issues()).containsExactly(Map.of("name",A.runId(),"reason","AMBIGUOUS_VERSION"));
    }
    @Test void caseInsensitiveCatalogCollisionsAreNotArbitrarilySelected() {
        var other=new RunRef("run-art-a",B.runVersionId());
        var result=V3NamedRunResolver.resolve(List.of(A.runId()),List.of(A,other),List.of());
        assertThat(result.references()).isEmpty();
        assertThat(result.issues()).containsExactly(Map.of("name",A.runId(),"reason","AMBIGUOUS_NAME"));
    }
    @Test void anAttachmentDoesNotSuppressAnotherExactlyNamedRun() {
        assertThat(resolve("RUN-ART-B 기록",List.of(A)).references()).containsExactly(B);
    }
    @Test void ordinaryTextDoesNotCreateOrSearchForImplicitRunNames() {
        var result=resolve("첨부한 실험의 기록 보여줘",List.of(A));
        assertThat(result.references()).isEmpty();
        assertThat(result.bindings()).isEmpty();
        assertThat(result.unresolved()).isEmpty();
    }
}
