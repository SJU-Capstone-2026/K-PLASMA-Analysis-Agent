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
    private final Clock clock;
    public RunRegistrationService(RunRepository repository,Clock clock) {this.repository=repository;this.clock=clock;}
    @Transactional
    public RunRef register(StoredSource source,ParsedScalars scalars,GraphBundle graphs) {
        var c=scalars.conditions(); var a=scalars.analysis();
        String runId=String.format(Locale.ROOT,"RUN-P%02d-S%03d-B%04d",(int)c.pressure(),(int)c.sourcePower(),(int)c.biasPower());
        repository.lock(runId);
        String version=UUID.randomUUID().toString(),registeredAt=clock.instant().toString();
        var metrics=new Metrics(scalars.ionFlux(),scalars.meanIonEnergy(),graphs.iedWidth());
        var analysisScalars=new AnalysisScalars(graphs.hasDistribution(),a.strictConvergence(),a.finalResidualMax(),a.electronTemperature(),a.ionTemperature(),a.gasTemperature(),a.absorbedPower(),a.alpha(),a.plasmaResistance(),a.plasmaReactance(),a.dcOffset(),a.peakToPeak(),a.currentDensityPeak(),a.electronDensity(),a.ionDensity(),a.metastableDensity(),a.neutralDensity(),a.ionFluxRaw(),a.metastableFluxRaw(),a.neutralFluxRaw());
        var analysis=new Analysis(graphs.hasDistribution(),a.strictConvergence(),a.finalResidualMax(),a.electronTemperature(),a.ionTemperature(),a.gasTemperature(),a.absorbedPower(),a.alpha(),a.plasmaResistance(),a.plasmaReactance(),a.dcOffset(),a.peakToPeak(),a.currentDensityPeak(),a.electronDensity(),a.ionDensity(),a.metastableDensity(),a.neutralDensity(),a.ionFluxRaw(),a.metastableFluxRaw(),a.neutralFluxRaw(),graphs.residualTrace(),graphs.iad(),graphs.iead(),graphs.current(),graphs.potential(),graphs.density());
        String note="실제 K-PLASMA(0D) 결과 파일에서 파싱한 Run";
        var summary=new Summary(runId,version,c.pressure(),c.sourcePower(),c.biasPower(),metrics,scalars.units(),"CONVERGED","VERIFIED","READY",registeredAt,100,note,analysisScalars);
        var full=new Full(runId,version,c.pressure(),c.sourcePower(),c.biasPower(),metrics,scalars.units(),"CONVERGED","VERIFIED","READY",registeredAt,100,note,analysis,graphs.iedDistribution(),graphs.sourceFiles());
        repository.save(source.sourceId(),summary,full);
        return new RunRef(runId,version);
    }
}
