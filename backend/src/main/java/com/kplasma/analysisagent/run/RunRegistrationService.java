package com.kplasma.analysisagent.run;

import com.kplasma.analysisagent.contract.RunDto.*;
import com.kplasma.analysisagent.ingestion.StoredSource;
import com.kplasma.analysisagent.parser.*;
import java.time.Clock;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Publishes immutable validated data and its current successful pointer in one transaction. */
@Service
public class RunRegistrationService {
    private final RunRepository repository;
    private final RunOutputSnapshotService outputSnapshots;
    private final Clock clock;
    public RunRegistrationService(RunRepository repository, RunOutputSnapshotService outputSnapshots, Clock clock) {
        this.repository = repository;
        this.outputSnapshots = outputSnapshots;
        this.clock = clock;
    }

    public RunRef newRef(ParsedScalars scalars) {
        var c = scalars.conditions();
        String runId = String.format(Locale.ROOT, "RUN-P%02d-S%03d-B%04d", (int)c.pressure(), (int)c.sourcePower(), (int)c.biasPower());
        return new RunRef(runId, UUID.randomUUID().toString());
    }

    @Transactional
    public RunRef register(StoredSource source, ParsedScalars scalars, GraphBundle graphs, RunRef ref) {
        var c=scalars.conditions(); var a=scalars.analysis();
        String runId = ref.runId();
        repository.lock(runId);
        String version=ref.runVersionId(),registeredAt=clock.instant().toString();
        var metrics=new Metrics(scalars.ionFlux(),scalars.meanIonEnergy(),graphs.iedWidth());
        var analysisScalars=new AnalysisScalars(graphs.hasDistribution(),a.strictConvergence(),a.finalResidualMax(),a.electronTemperature(),a.ionTemperature(),a.gasTemperature(),a.absorbedPower(),a.alpha(),a.plasmaResistance(),a.plasmaReactance(),a.dcOffset(),a.peakToPeak(),a.currentDensityPeak(),a.electronDensity(),a.ionDensity(),a.metastableDensity(),a.neutralDensity(),a.ionFluxRaw(),a.metastableFluxRaw(),a.neutralFluxRaw());
        var analysis=new Analysis(graphs.hasDistribution(),a.strictConvergence(),a.finalResidualMax(),a.electronTemperature(),a.ionTemperature(),a.gasTemperature(),a.absorbedPower(),a.alpha(),a.plasmaResistance(),a.plasmaReactance(),a.dcOffset(),a.peakToPeak(),a.currentDensityPeak(),a.electronDensity(),a.ionDensity(),a.metastableDensity(),a.neutralDensity(),a.ionFluxRaw(),a.metastableFluxRaw(),a.neutralFluxRaw(),List.of(),null,null,null,null,null);
        String note="실제 K-PLASMA(0D) 결과 파일에서 파싱한 Run";
        var summary=new Summary(runId,version,c.pressure(),c.sourcePower(),c.biasPower(),metrics,scalars.units(),"CONVERGED","VERIFIED","READY",registeredAt,100,note,analysisScalars);
        var full=new Full(runId,version,c.pressure(),c.sourcePower(),c.biasPower(),metrics,scalars.units(),"CONVERGED","VERIFIED","READY",registeredAt,100,note,analysis,List.of(),graphs.sourceFiles());
        repository.save(source.sourceId(),summary,full);
        graphs.outputs().forEach(outputSnapshots::save);
        return ref;
    }
}
