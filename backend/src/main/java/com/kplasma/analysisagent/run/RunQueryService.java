package com.kplasma.analysisagent.run;
import com.kplasma.analysisagent.contract.RunDto;
import java.util.*;
import org.springframework.stereotype.Service;
@Service
public class RunQueryService {
    private final RunRepository repository;
    public RunQueryService(RunRepository repository) {this.repository=repository;}
    public List<RunDto.Summary> listSearchable() {return repository.searchable();}
    public RunDto.Full getVersion(UUID id) {return repository.version(id);}
}
